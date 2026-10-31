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
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RTL = HERE / "rtl/irq_pending.sv"
TB = HERE / "tb/irq_tb.sv"
CDC = HERE / "tb/cdc_delay_model.sv"
RECEIVER = HERE / "rtl/cdc_receiver.sv"


class RunInterrupted(BaseException):
    def __init__(self, signum):
        self.signum = signum


def resolve_tools(args):
    """Resolve CLI executables before a runner changes its child working directory.

    Keep symlinks intact: resolving a venv's Python to its real path loses the venv.
    Missing commands stay unchanged so the normal error handling records the failure.
    """
    for name in ("iverilog", "vvp", "verilator", "yosys", "sby", "smtbmc", "witness",
                 "solver", "cc", "coverage_tool", "sta", "python", "formal_python",
                 "cocotb_python", "rdl_python"):
        value = getattr(args, name, None)
        if value is not None:
            found = shutil.which(os.fspath(value))
            if found is not None:
                setattr(args, name, os.path.abspath(found))


def interrupted(signum, _frame):
    raise RunInterrupted(signum)


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
        case["coverage"] = ([f"atomic/p{case['initial']}/en{case['enabled']}/op{case['op']}"]
                            if case["mode"] == "atomic" else
                            [f"cross/p{case['initial']}/en{case['enabled']}/edge{case['edge']}"]
                            if case["mode"] == "cross" else [])
    for scenario in range(3):
        cases.append(dict(id=f"reset-scenario{scenario}", mode="reset", initial=0,
                          enabled=1, scenario=scenario, checks=7,
                          coverage=[f"reset/scenario{scenario}"]))
    pairs = [(a, b) for a in (1, 2, 3) for b in (1, 2, 3)]
    random.Random(seed).shuffle(pairs)
    cdc_vectors = [list(pair) for pair in pairs for _ in range(2)]
    cdc_case = dict(id=f"cdc-seed{seed}", mode="cdc", initial=0, enabled=1,
                    vectors=cdc_vectors, seed=seed,
                    checks=2 + sum(max(row) + 2 for row in cdc_vectors),
                    coverage=[f"cdc/a{a-2}/b{b-2}/value{v}"
                              for a, b in pairs for v in (1, 0)])
    cases.append(cdc_case)
    for case in cases:
        case.update(mutation=int(demo_bug), expected_failure=None, category="functional")
    cases.extend([
        dict(id="detect-clear-priority", mode="cross", initial=0, enabled=1,
             edge=0, checks=5, mutation=1, expected_failure="IRQ_SET_WINS", coverage=[]),
        dict(id="detect-masked-storage", mode="atomic", initial=0, enabled=0,
             op=1, checks=3, mutation=2, expected_failure="IRQ_SET_ONLY", coverage=[]),
        dict(id="detect-reset-while-pending", mode="reset", initial=0, enabled=1,
             scenario=0, checks=7, mutation=3, expected_failure="IRQ_RESET", coverage=[]),
        dict(cdc_case, id="detect-cdc-early-receiver", mutation=4,
             expected_failure="CDC_RECEIVER_EARLY", coverage=[]),
    ])
    for case in cases:
        if case["expected_failure"]:
            case["category"] = "mutation"
    cases.append(dict(id="detect-x-propagation", mode="x", initial=0, enabled=1,
                      checks=4, mutation=0, expected_failure="IRQ_OUTPUT_UNKNOWN",
                      category="checker-selftest", coverage=["x/propagation-detected"]))
    return cases


def execute(command, log, timeout, cwd):
    started = time.monotonic()
    error = None
    code = None
    with log.open("w", encoding="utf-8") as stream:
        proc = None
        try:
            proc = subprocess.Popen(command, cwd=cwd, stdout=stream,
                                    stderr=subprocess.STDOUT, start_new_session=True)
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            error = "command timeout"
            cleanup_error = stop_process_group(proc)
            if cleanup_error:
                error += "; " + cleanup_error
        except OSError as exc:
            error = str(exc)
        except BaseException:
            cleanup_error = stop_process_group(proc)
            if cleanup_error:
                stream.write(f"\nRUNNER_ERROR {cleanup_error}\n")
            raise
        if error:
            stream.write(f"\nRUNNER_ERROR {error}\n")
    return dict(command=command, returncode=code, error=error,
                seconds=time.monotonic() - started)


def stop_process_group(proc):
    """Try group cleanup, preserve failures as evidence and bound the final wait."""
    if proc is None:
        return None
    error = None
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        # A denied group signal must not discard summary/JUnit output. Killing
        # the direct child is a fallback, not evidence that descendants stopped.
        error = f"process group termination failed: {exc}"
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        except OSError as child_error:
            error += f"; direct child termination failed: {child_error}"
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        error = (error + "; " if error else "") + f"process cleanup incomplete: {exc}"
    return error


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


def write_junit(out, cases, results, coverage):
    suite = ET.Element("testsuite", name="irq-regression", tests=str(len(cases) + 1),
                       failures=str(sum(r["status"] == "fail" for r in results) +
                                    (not coverage["success"])),
                       errors=str(sum(r["status"] == "error" for r in results)),
                       time=f"{sum(r['seconds'] for r in results):.6f}")
    for case, result in zip(cases, results):
        node = ET.SubElement(suite, "testcase", name=case["id"],
                             classname="irq." + case["category"],
                             time=f"{result['seconds']:.6f}")
        if result["status"] in ("fail", "error"):
            problem = ET.SubElement(node, "failure" if result["status"] == "fail" else "error",
                                    message=result["message"])
            problem.text = f"See {result['log']} and manifest.json"
        ET.SubElement(node, "system-out").text = result["message"]
    gate = ET.SubElement(suite, "testcase", name="requirements-and-coverage",
                         classname="irq.gate", time="0")
    if not coverage["success"]:
        ET.SubElement(gate, "failure", message="required coverage incomplete").text = (
            "See coverage.json: " + ", ".join(coverage["missing"]))
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)


def run(args):
    out = args.out.resolve()
    # A fresh directory prevents stale results from becoming a new run's evidence.
    out.mkdir(parents=True, exist_ok=False)
    catalog = json.loads(args.requirements.read_text(encoding="utf-8"))
    requirements = catalog["requirements"]
    if not requirements or len({r["id"] for r in requirements}) != len(requirements):
        raise ValueError("requirements must be nonempty and have unique IDs")
    for requirement in requirements:
        if not requirement["goals"] or len(set(requirement["goals"])) != len(requirement["goals"]):
            raise ValueError("each requirement needs nonempty, unique goals")
    cases = make_plan(args.profile, args.seed, args.demo_bug)
    for case in cases:
        case["requirement_ids"] = [r["id"] for r in requirements
                                   if set(case["coverage"]) & set(r["goals"])]
    inputs = [RTL, TB, CDC, RECEIVER, args.requirements.resolve(), HERE / "run.py"]
    manifest = dict(
        schema_version=2, profile=args.profile, seed=args.seed, demo_bug=args.demo_bug,
        created_at=datetime.now(timezone.utc).isoformat(),
        python=sys.version, timeout_seconds=args.timeout,
        source_sha256={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):
                       hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in inputs}, cases=cases,
    )
    write_json(out / "manifest.json", manifest)
    write_json(out / "requirements.json", catalog)
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
                   str(RTL), str(RECEIVER), str(CDC), str(TB)]
        build_log = out / f"build-{mutation}.log"
        builds[mutation] = execute(command, build_log, 30, out)
        if builds[mutation]["error"] or builds[mutation]["returncode"] != 0:
            print(f"BUILD_ERROR mutation={mutation}\n" +
                  build_log.read_text(encoding="utf-8", errors="replace"), flush=True)
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
        elif case["mode"] == "reset":
            command.append(f"+SCENARIO={case['scenario']}")
        elif case["mode"] in ("random", "cdc"):
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
        observed = sorted(set(re.findall(r"^COVER (\S+)$",
                                        log.read_text(encoding="utf-8", errors="replace"), re.MULTILINE)))
        if status in ("pass", "detected") and set(case["coverage"]) - set(observed):
            status, message = "error", "required case coverage marker missing"
        result = dict(id=case["id"], status=status, message=message,
                      coverage=observed,
                      credited_coverage=sorted(set(observed) & set(case["coverage"]))
                      if status in ("pass", "detected") else [],
                      log=str(log.relative_to(out)), **execution)
        results.append(result)
        write_json(directory / "result.json", result)
        print(f"{status.upper():8} {case['id']}: {message}", flush=True)
    complete = [r["id"] for r in results] == [c["id"] for c in cases]
    groups = {}
    for name, category in (("functional", "functional"), ("mutations", "mutation"),
                           ("checker_selftests", "checker-selftest")):
        selected = [r for c, r in zip(cases, results) if c["category"] == category]
        groups[name] = dict(planned=len(selected), **{
            status: sum(r["status"] == status for r in selected)
            for status in ("pass", "detected", "fail", "error")})
    hits = {}
    for result in results:
        if result["status"] in ("pass", "detected"):
            for goal in result["credited_coverage"]:
                hits.setdefault(goal, []).append(result["id"])
    required = {goal for r in requirements for goal in r["goals"]}
    coverage = dict(success=required <= hits.keys(), required=len(required),
                    hit=len(required & hits.keys()), missing=sorted(required - hits.keys()),
                    hits=hits, requirements=[dict(r, passed=set(r["goals"]) <= hits.keys())
                                            for r in requirements])
    write_json(out / "coverage.json", coverage)
    success = complete and coverage["success"] and all(r["status"] in ("pass", "detected") for r in results)
    write_json(out / "summary.json", dict(success=success, complete=complete,
                                         planned=len(cases), results=len(results),
                                         coverage_hit=coverage["hit"], coverage_required=coverage["required"],
                                         **groups))
    write_junit(out, cases, results, coverage)
    print(f"Coverage: {coverage['hit']}/{coverage['required']} required goals")
    print(f"Artifacts: {out}\nRegression: {'PASS' if success else 'FAIL'}")
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--demo-bug", choices=("0", "1"), default="0")
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--requirements", type=Path, default=HERE / "requirements.json")
    parser.add_argument("--timeout", type=float, default=10.0, help="per simulation/tool probe seconds")
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    resolve_tools(args)
    if os.name != "posix":
        parser.error("this example requires a POSIX host (Linux or macOS)")
    if args.seed < 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("seed must be nonnegative; timeout must be finite and positive")
    if args.out.exists():
        parser.error("output directory already exists; select a new --out directory")
    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        return run(args)
    except RunInterrupted as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
