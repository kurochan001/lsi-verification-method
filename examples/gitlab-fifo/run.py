#!/usr/bin/env python3
"""FIFO regression with recorded random vectors, scoreboard checks and JUnit."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUPPORT_PATH = HERE.parent / "gitlab-regression/run.py"
SPEC = importlib.util.spec_from_file_location("irq_regression_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)
write_json = SUPPORT.write_json


def boundary_vectors(depth, width):
    """Ensure boundary coverage without depending on random luck."""
    ones = (1 << width) - 1
    vectors = [[0, 0, 0, 0]]
    # Reinitialize each state/op, so earlier operations cannot change its meaning.
    for state_count in sorted({0, depth, *([1] if depth > 1 else [])}):
        for op in range(4):
            vectors.append([0, 0, 0, 0])
            vectors.extend([[1, 1, 0, ones] for _ in range(state_count)])
            vectors.append([1, op & 1, (op >> 1) & 1, ones // 3])
    # Transfer all significant patterns, wrap repeatedly, and drain afterwards.
    vectors.append([0, 0, 0, 0])
    for pattern in (0, ones, ones // 3):
        for _ in range(2):
            vectors.extend([[1, 1, 0, pattern] for _ in range(depth)])
            vectors.extend([[1, 0, 1, 0] for _ in range(depth)])
    # Flush pending data, then check the first post-reset transfer independently.
    vectors.extend([[1, 1, 0, ones], [0, 1, 1, ones],
                    [1, 1, 0, ones // 3], [1, 0, 1, 0]])
    vectors.extend([[1, 0, 1, 0] for _ in range(depth)])
    return vectors


def random_vectors(depth, width, seed, cycles):
    rng = random.Random(seed)
    ones = (1 << width) - 1
    vectors = [[0, 0, 0, 0]]
    for _ in range(cycles):
        data = rng.choice((0, ones, ones // 3, rng.getrandbits(width)))
        vectors.append([int(rng.randrange(32) != 0), rng.randrange(2), rng.randrange(2), data])
    # End with a drain, not a reset that would silently discard unchecked data.
    vectors.extend([[1, 0, 1, 0] for _ in range(depth + 1)])
    return vectors


def make_plan(args):
    prefix = f"d{args.depth}-w{args.width}"
    baseline = boundary_vectors(args.depth, args.width)
    cases = [dict(id=f"{prefix}-boundaries", vectors=baseline,
                  mutation=args.demo_bug, expected_failure=None, category="functional")]
    seeds = range(args.seed, args.seed + (3 if args.profile == "nightly" else 1))
    for seed in seeds:
        cases.append(dict(id=f"{prefix}-random-seed{seed}", seed=seed,
                          vectors=random_vectors(args.depth, args.width, seed, args.cycles),
                          mutation=args.demo_bug, expected_failure=None, category="functional"))
    for mutation, label in ((1, "FIFO_DATA_ORDER"), (2, "FIFO_COUNT"), (3, "FIFO_RESET")):
        cases.append(dict(id=f"{prefix}-detect-mutation{mutation}", vectors=baseline,
                          mutation=mutation, expected_failure=label, category="mutation"))
    for case in cases:
        case["checks"] = len(case["vectors"])
    return cases


def load_catalog(path, depth):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    requirements = catalog["requirements"]
    if not requirements:
        raise ValueError("requirements must be nonempty")
    ids = set()
    for requirement in requirements:
        rid = requirement["id"]
        goals = requirement["goals"]
        minimum = requirement.get("minimum_depth", 1)
        if (not isinstance(rid, str) or not rid or rid in ids or
                not isinstance(goals, list) or not goals or
                any(not isinstance(g, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", g) for g in goals) or
                len(goals) != len(set(goals)) or type(minimum) is not int or minimum < 1):
            raise ValueError("invalid/duplicate requirement ID, goals or minimum_depth")
        ids.add(rid)
    applicable = [r for r in requirements if depth >= r.get("minimum_depth", 1)]
    if not applicable:
        raise ValueError("no applicable requirements")
    excluded = [dict(id=r["id"], reason=f"depth {depth} < minimum_depth {r['minimum_depth']}")
                for r in requirements if r not in applicable]
    return catalog, applicable, excluded


def junit(out, args, results, coverage):
    classname = f"fifo.d{args.depth}.w{args.width}"
    suite = ET.Element("testsuite", name=classname, tests=str(len(results) + 1),
                       failures=str(sum(r["status"] == "fail" for r in results) + int(not coverage["success"])),
                       errors=str(sum(r["status"] == "error" for r in results)))
    for result in results:
        case = ET.SubElement(suite, "testcase", name=result["id"],
                             classname=classname + "." + result["category"],
                             time=f"{result['seconds']:.6f}")
        if result["status"] in ("fail", "error"):
            ET.SubElement(case, "failure" if result["status"] == "fail" else "error",
                          message=result["message"]).text = f"See {result['log']} and manifest.json"
    gate = ET.SubElement(suite, "testcase", name=f"d{args.depth}-w{args.width}-requirements-and-coverage",
                         classname=classname + ".gate")
    if not coverage["success"]:
        ET.SubElement(gate, "failure", message="required coverage incomplete").text = ", ".join(coverage["missing"])
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)


def run(args):
    catalog, requirements, excluded = load_catalog(args.requirements, args.depth)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases = make_plan(args)
    inputs = [HERE / "rtl/sync_fifo.sv", HERE / "tb/fifo_tb.sv", HERE / "run.py",
              SUPPORT_PATH, args.requirements.resolve(), HERE / "gitlab-ci.yml",
              HERE.parent / "gitlab-regression/gitlab-ci.yml", ROOT / ".gitlab-ci.yml"]
    write_json(out / "manifest.json", dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        configuration=dict(depth=args.depth, width=args.width), profile=args.profile,
        seed=args.seed, random_cycles=args.cycles, demo_bug=args.demo_bug,
        timeout_seconds=args.timeout, python=sys.version,
        ci={key: os.environ.get(key) for key in ("CI_COMMIT_SHA", "CI_PIPELINE_ID", "CI_JOB_ID")},
        source_sha256={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):
                       hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}, cases=cases))
    write_json(out / "requirements.json", catalog)
    tools = {}
    for name, command in (("iverilog", [args.iverilog, "-V"]), ("vvp", [args.vvp, "-V"])):
        log = out / f"{name}-version.log"
        execution = SUPPORT.execute(command, log, args.timeout, out)
        tools[name] = dict(execution, output=log.read_text(encoding="utf-8", errors="replace"))
    write_json(out / "tools.json", tools)
    builds = {}
    for mutation in sorted({c["mutation"] for c in cases}):
        command = [args.iverilog, "-g2012", "-s", "fifo_tb",
                   f"-Pfifo_tb.DEPTH={args.depth}", f"-Pfifo_tb.WIDTH={args.width}",
                   f"-Pfifo_tb.MUTATION={mutation}", "-o", str(out / f"fifo-{mutation}.vvp"),
                   str(HERE / "rtl/sync_fifo.sv"), str(HERE / "tb/fifo_tb.sv")]
        builds[mutation] = SUPPORT.execute(command, out / f"build-{mutation}.log", args.timeout, out)
    write_json(out / "builds.json", builds)
    results = []
    hits = {}
    for case in cases:
        directory = out / case["id"]
        directory.mkdir()
        vector_path = directory / "vectors.txt"
        vector_path.write_text("".join(f"{rst} {wr} {rd} {data:x}\n" for rst, wr, rd, data in case["vectors"]), encoding="utf-8")
        log = directory / "simulation.log"
        command = [args.vvp, str(out / f"fifo-{case['mutation']}.vvp"),
                   f"+VECTORS={vector_path}", f"+WAVE={directory / 'wave.vcd'}"]
        build = builds[case["mutation"]]
        if build["error"] or build["returncode"] != 0:
            execution = dict(command=command, returncode=None, seconds=0,
                             error=f"build failed; see build-{case['mutation']}.log")
            log.write_text(execution["error"] + "\n", encoding="utf-8")
        else:
            execution = SUPPORT.execute(command, log, args.timeout, directory)
        output = log.read_text(encoding="utf-8", errors="replace")
        status, message = SUPPORT.classify(case, execution, output)
        observed = sorted(set(re.findall(r"^COVER (\S+)$", output, re.MULTILINE)))
        # A mutant can demonstrate sensitivity, but cannot complete normal goals.
        credited = observed if status == "pass" and case["category"] == "functional" else []
        for goal in credited:
            hits.setdefault(goal, []).append(case["id"])
        result = dict(id=case["id"], category=case["category"], status=status, message=message,
                      observed_coverage=observed, credited_coverage=credited,
                      log=str(log.relative_to(out)), **execution)
        results.append(result)
        write_json(directory / "result.json", result)
        print(f"{status.upper():8} {case['id']}: {message}", flush=True)
    required = {goal for r in requirements for goal in r["goals"]}
    coverage = dict(success=required <= hits.keys(), required=len(required),
                    hit=len(required & hits.keys()), hits=hits,
                    missing=sorted(required - hits.keys()), excluded=excluded,
                    requirements=[dict(r, passed=set(r["goals"]) <= hits.keys()) for r in requirements])
    complete = [r["id"] for r in results] == [c["id"] for c in cases]
    success = complete and coverage["success"] and all(r["status"] in ("pass", "detected") for r in results)
    write_json(out / "coverage.json", coverage)
    write_json(out / "summary.json", dict(success=success, complete=complete,
                                         planned=len(cases), results=len(results),
                                         functional_pass=sum(r["category"] == "functional" and r["status"] == "pass" for r in results),
                                         mutations_detected=sum(r["status"] == "detected" for r in results),
                                         coverage_hit=coverage["hit"], coverage_required=coverage["required"]))
    junit(out, args, results, coverage)
    print(f"Coverage: {coverage['hit']}/{coverage['required']} required goals")
    print(f"Artifacts: {out}\nRegression: {'PASS' if success else 'FAIL'}")
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, choices=(1, 3, 8), default=3)
    parser.add_argument("--width", type=int, choices=(8, 16), default=8)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--cycles", type=int, help="random cycles per seed (smoke: 200, nightly: 2000)")
    parser.add_argument("--demo-bug", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--requirements", type=Path, default=HERE / "requirements.json")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("fifo-local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    if args.cycles is None:
        args.cycles = 2000 if args.profile == "nightly" else 200
    if os.name != "posix" or args.seed < 0 or not 1 <= args.cycles <= 10000 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("requires POSIX, nonnegative seed, 1..10000 cycles and a finite positive timeout")
    if args.out.exists():
        parser.error("output directory already exists; select a new --out")
    previous = signal.signal(signal.SIGTERM, SUPPORT.interrupted)
    try:
        return run(args)
    except SUPPORT.RunInterrupted as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"RUNNER_ERROR {exc}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
