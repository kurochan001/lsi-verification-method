#!/usr/bin/env python3
"""Ready/valid regression with legal held inputs, queue checks and transfer accounting."""

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
SUPPORT_PATH = HERE.parent / "local-irq-cdc/run.py"
SPEC = importlib.util.spec_from_file_location("irq_regression_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)
write_json = SUPPORT.write_json


class Stimulus:
    """Generate legal source holds using the specified capacity, never the DUT."""
    def __init__(self, depth):
        self.depth = depth
        self.count = 0
        self.held = None
        self.vectors = []

    def cycle(self, offer=0, ready=0, data=0, reset=False):
        valid = 1 if self.held is not None else offer
        value = self.held if self.held is not None else data
        self.vectors.append([int(not reset), valid, ready, value])
        if reset:
            self.count = 0
            self.held = None
            return
        pop = self.count > 0 and ready
        push = valid and (self.count < self.depth or pop)
        self.count += int(bool(push)) - int(bool(pop))
        self.held = value if valid and not push else None

    def drain(self):
        while self.count or self.held is not None:
            self.cycle(ready=1)
        self.cycle(ready=1)


def boundary_vectors(depth, width):
    source = Stimulus(depth)
    source.cycle(reset=True)
    # An isolated consumption exposes a duplicated output immediately.
    source.cycle(offer=1, data=0xa5)
    source.cycle(ready=1)
    for occupancy in sorted({0, depth, *([1] if depth > 1 else [])}):
        for valid in (0, 1):
            for ready in (0, 1):
                source.cycle(reset=True)
                for i in range(occupancy):
                    source.cycle(offer=1, data=0x20 + i)
                source.cycle(offer=valid, ready=ready, data=0x55)
                source.drain()
    # Verify representative payloads and multiple pointer wraparounds.
    source.cycle(reset=True)
    for data in (0, (1 << width) - 1, ((1 << width) - 1) // 3):
        for _ in range(2 * depth + 2):
            source.cycle(offer=1, ready=1, data=data)
    source.drain()
    # Cancel both buffered items and an unaccepted source offer by reset.
    for i in range(depth):
        source.cycle(offer=1, data=0x40 + i)
    source.cycle(offer=1, data=0x77)
    source.cycle(reset=True)
    source.cycle(offer=1, data=0x99)
    source.drain()
    return source.vectors


def random_vectors(depth, width, seed, cycles):
    rng = random.Random(seed)
    source = Stimulus(depth)
    source.cycle(reset=True)
    for _ in range(cycles):
        source.cycle(offer=int(rng.randrange(4) != 0), ready=int(rng.randrange(3) == 0),
                     data=rng.choice((0, (1 << width) - 1, ((1 << width) - 1) // 3,
                                      rng.getrandbits(width))), reset=rng.randrange(64) == 0)
    source.drain()
    return source.vectors


def expected_accounting(vectors, depth):
    count = accepted = delivered = flushed = 0
    for rst, valid, ready, _ in vectors:
        if not rst:
            flushed += count
            count = 0
            continue
        pop = count > 0 and ready
        push = valid and (count < depth or pop)
        count += int(bool(push)) - int(bool(pop))
        accepted += int(bool(push))
        delivered += int(bool(pop))
    return [accepted, delivered, flushed]


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
    for mutation, label in ((1, "STREAM_STABILITY"), (2, "STREAM_DATA"), (3, "STREAM_VALID")):
        cases.append(dict(id=f"{prefix}-detect-mutation{mutation}", vectors=baseline,
                          mutation=mutation, expected_failure=label, category="mutation"))
    for case in cases:
        case["checks"] = len(case["vectors"])
        case["accounting"] = expected_accounting(case["vectors"], args.depth)
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
    classname = f"stream.d{args.depth}.w{args.width}"
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
    inputs = [HERE / "rtl/stream_buffer.sv", HERE / "tb/stream_tb.sv", HERE / "run.py",
              SUPPORT_PATH, args.requirements.resolve()]
    write_json(out / "manifest.json", dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        configuration=dict(depth=args.depth, width=args.width), profile=args.profile,
        seed=args.seed, random_cycles=args.cycles, demo_bug=args.demo_bug,
        timeout_seconds=args.timeout, python=sys.version,
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
        command = [args.iverilog, "-g2012", "-s", "stream_tb",
                   f"-Pstream_tb.DEPTH={args.depth}", f"-Pstream_tb.WIDTH={args.width}",
                   f"-Pstream_tb.MUTATION={mutation}", "-o", str(out / f"stream-{mutation}.vvp"),
                   str(HERE / "rtl/stream_buffer.sv"), str(HERE / "tb/stream_tb.sv")]
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
        command = [args.vvp, str(out / f"stream-{case['mutation']}.vvp"),
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
        if status == "pass":
            ledgers = re.findall(r"^ACCOUNTING accepted=(\d+) delivered=(\d+) flushed=(\d+)$",
                                 output, re.MULTILINE)
            if len(ledgers) != 1 or list(map(int, ledgers[0])) != case["accounting"]:
                status, message = "error", "missing or mismatched transfer accounting"
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
    parser.add_argument("--depth", type=int, choices=(1, 3), default=3)
    parser.add_argument("--width", type=int, choices=(8, 16), default=8)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--cycles", type=int, help="random cycles per seed (smoke: 200, nightly: 2000)")
    parser.add_argument("--demo-bug", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--requirements", type=Path, default=HERE / "requirements.json")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("stream-local-%Y%m%dT%H%M%S%fZ"))
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
