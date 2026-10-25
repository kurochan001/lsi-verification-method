#!/usr/bin/env python3
"""Small, standalone IRQ regression; Python 3.10+ and Icarus Verilog."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RTL = HERE / "rtl/irq_pending.sv"
TB = HERE / "tb/irq_tb.sv"


def make_plan(profile, seed, demo_bug):
    cases = []
    for initial in (0, 1):
        for enabled in (0, 1):
            for op in range(4):
                cases.append(dict(id=f"atomic-p{initial}-en{enabled}-op{op}",
                                  mode="atomic", initial=initial, enabled=enabled,
                                  op=op, checks=3))
            for edge in (-1, 0, 1):
                cases.append(dict(id=f"cross-p{initial}-en{enabled}-edge{edge}",
                                  mode="cross", initial=initial, enabled=enabled,
                                  edge=edge, checks=5))
    if profile == "nightly":
        for value in range(seed, seed + 3):
            rng = random.Random(value)
            vectors = [[rng.randrange(2) for _ in range(3)] for _ in range(64)]
            cases.append(dict(id=f"random-seed{value}", mode="random", initial=0,
                              enabled=1, vectors=vectors, seed=value, checks=66))
    for case in cases:
        case.update(mutation=int(demo_bug), expected_failure=None)
    cases.extend([
        dict(id="detect-clear-priority", mode="cross", initial=0, enabled=1,
             edge=0, checks=5, mutation=1, expected_failure="IRQ_SET_WINS"),
        dict(id="detect-masked-storage", mode="atomic", initial=0, enabled=0,
             op=1, checks=3, mutation=2, expected_failure="IRQ_SET_ONLY"),
    ])
    return cases


def execute(command, log, timeout, cwd):
    started = time.monotonic()
    error = None
    code = None
    with log.open("w", encoding="utf-8") as stream:
        try:
            proc = subprocess.run(command, cwd=cwd, stdout=stream,
                                  stderr=subprocess.STDOUT, timeout=timeout,
                                  check=False)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            error = "command timeout"
        except OSError as exc:
            error = str(exc)
        if error:
            stream.write(f"\nRUNNER_ERROR {error}\n")
    return dict(command=command, returncode=code, error=error,
                seconds=time.monotonic() - started)


def classify(case, execution, output):
    if execution["error"]:
        return "error", execution["error"]
    failures = re.findall(r"^CHECK_FAIL (\w+)$", output, re.MULTILINE)
    passes = re.findall(r"^RESULT PASS checks=(\d+)$", output, re.MULTILINE)
    completed = (execution["returncode"] == 0 and not failures and
                 passes == [str(case["checks"])])
    expected = case["expected_failure"]
    if expected:
        if execution["returncode"] != 0 and failures == [expected] and not passes:
            return "detected", f"expected mutation detected by {expected}"
        if completed:
            return "fail", f"mutation survived; expected {expected}"
        return "error", "mutation did not fail through the expected checker"
    if completed:
        return "pass", f"{case['checks']} checked cycles"
    if execution["returncode"] != 0 and failures:
        return "fail", "checker failure: " + ", ".join(failures)
    return "error", "missing/invalid completion marker or unexpected exit"


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def write_junit(out, cases, results):
    suite = ET.Element("testsuite", name="irq-regression", tests=str(len(cases)),
                       failures=str(sum(r["status"] == "fail" for r in results)),
                       errors=str(sum(r["status"] == "error" for r in results)),
                       time=f"{sum(r['seconds'] for r in results):.6f}")
    for case, result in zip(cases, results):
        node = ET.SubElement(suite, "testcase", name=case["id"],
                             classname="irq.mutation" if case["expected_failure"] else "irq.functional",
                             time=f"{result['seconds']:.6f}")
        if result["status"] in ("fail", "error"):
            problem = ET.SubElement(node, "failure" if result["status"] == "fail" else "error",
                                    message=result["message"])
            problem.text = f"See {result['log']} and manifest.json"
        ET.SubElement(node, "system-out").text = result["message"]
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)


def run(args):
    out = args.out.resolve()
    # A fresh directory prevents stale results from becoming a new run's evidence.
    out.mkdir(parents=True, exist_ok=False)
    cases = make_plan(args.profile, args.seed, args.demo_bug)
    inputs = [RTL, TB, HERE / "run.py", HERE / "gitlab-ci.yml", ROOT / ".gitlab-ci.yml"]
    manifest = dict(
        schema_version=1, profile=args.profile, seed=args.seed, demo_bug=args.demo_bug,
        created_at=datetime.now(timezone.utc).isoformat(),
        ci={key: os.environ.get(key) for key in
            ("CI_COMMIT_SHA", "CI_PIPELINE_ID", "CI_JOB_ID")},
        python=sys.version, timeout_seconds=args.timeout,
        source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in inputs}, cases=cases,
    )
    write_json(out / "manifest.json", manifest)
    versions = {}
    for name, command in (("iverilog", [args.iverilog, "-V"]), ("vvp", [args.vvp, "-V"])):
        log = out / f"{name}-version.log"
        execute(command, log, args.timeout, out)
        versions[name] = log.read_text(encoding="utf-8", errors="replace")
    write_json(out / "tools.json", versions)
    builds = {}
    for mutation in sorted({case["mutation"] for case in cases}):
        command = [args.iverilog, "-g2012", "-s", "irq_tb",
                   f"-Pirq_tb.MUTATION={mutation}", "-o", str(out / f"irq-{mutation}.vvp"),
                   str(RTL), str(TB)]
        builds[mutation] = execute(command, out / f"build-{mutation}.log", 30, out)
    write_json(out / "builds.json", builds)
    results = []
    for case in cases:
        directory = out / case["id"]
        directory.mkdir()
        log = directory / "simulation.log"
        command = [args.vvp, str(out / f"irq-{case['mutation']}.vvp"),
                   f"+MODE={case['mode']}", f"+INITIAL={case['initial']}",
                   f"+ENABLE={case['enabled']}", f"+WAVE={directory / 'wave.vcd'}"]
        if case["mode"] == "atomic":
            command.append(f"+OP={case['op']}")
        elif case["mode"] == "cross":
            command.append(f"+EVENT_EDGE={case['edge']}")
        else:
            path = directory / "vectors.txt"
            path.write_text("".join(" ".join(map(str, row)) + "\n" for row in case["vectors"]),
                            encoding="utf-8")
            command.append(f"+VECTORS={path}")
        build = builds[case["mutation"]]
        if build["error"] or build["returncode"] != 0:
            execution = dict(command=command, returncode=None, seconds=0,
                             error=f"build failed; see build-{case['mutation']}.log")
            log.write_text(execution["error"] + "\n", encoding="utf-8")
        else:
            execution = execute(command, log, args.timeout, directory)
        status, message = classify(case, execution, log.read_text(encoding="utf-8", errors="replace"))
        result = dict(id=case["id"], status=status, message=message,
                      log=str(log.relative_to(out)), **execution)
        results.append(result)
        write_json(directory / "result.json", result)
        print(f"{status.upper():8} {case['id']}: {message}", flush=True)
    complete = [r["id"] for r in results] == [c["id"] for c in cases]
    groups = {}
    for name, expected in (("functional", False), ("mutations", True)):
        selected = [r for c, r in zip(cases, results) if bool(c["expected_failure"]) == expected]
        groups[name] = dict(planned=len(selected), **{
            status: sum(r["status"] == status for r in selected)
            for status in ("pass", "detected", "fail", "error")})
    success = complete and all(r["status"] in ("pass", "detected") for r in results)
    write_json(out / "summary.json", dict(success=success, complete=complete,
                                         planned=len(cases), results=len(results), **groups))
    write_junit(out, cases, results)
    print(f"Artifacts: {out}\nRegression: {'PASS' if success else 'FAIL'}")
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--demo-bug", choices=("0", "1"), default="0")
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--timeout", type=float, default=10.0, help="per simulation/tool probe seconds")
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    if args.seed < 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("seed must be nonnegative; timeout must be finite and positive")
    if args.out.exists():
        parser.error("output directory already exists; select a new --out directory")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
