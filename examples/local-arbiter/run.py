#!/usr/bin/env python3
"""Round-robin arbitration regression with persistent requests and conditional fairness."""

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


class Requests:
    """Legal persistent requests, planned from the specification only."""
    def __init__(self, ports):
        self.ports = ports
        self.pending = 0
        self.order = list(range(ports))
        self.locked = None
        self.vectors = []

    def cycle(self, offers=0, ready=0, reset=False):
        req = 0 if reset else offers | self.pending
        self.vectors.append([int(not reset), req, ready])
        if reset:
            self.pending = 0
            self.order = list(range(self.ports))
            self.locked = None
            return
        winner = self.locked
        if winner is None:
            winner = next((p for p in self.order if req & (1 << p)), None)
        if winner is not None and ready:
            self.pending = req & ~(1 << winner)
            pos = self.order.index(winner)
            self.order = self.order[pos + 1:] + self.order[:pos + 1]
            self.locked = None
        else:
            self.pending = req
            self.locked = winner

    def drain(self):
        while self.pending:
            self.cycle(ready=1)
        self.cycle(ready=1)


def boundary_vectors(ports):
    source = Requests(ports)
    all_ports = (1 << ports) - 1
    for mask in range(1 << ports):
        for ready in (0, 1):
            source.cycle(reset=True)
            source.cycle(offers=mask, ready=ready)
            source.drain()
    # Continuous contention exercises every winner, rotation and fairness window.
    source.cycle(reset=True)
    for _ in range(3 * ports):
        source.cycle(offers=all_ports, ready=1)
    source.drain()
    # New high-priority requests cannot replace a stalled selected requester.
    source.cycle(reset=True)
    source.cycle(offers=1 << (ports - 1))
    source.cycle(offers=1)
    source.cycle(ready=1)
    source.drain()
    # Reset cancels waiting requests and the locked selection, then recover.
    source.cycle(offers=all_ports)
    source.cycle(reset=True)
    source.cycle(offers=all_ports, ready=1)
    source.drain()
    return source.vectors


def random_vectors(ports, seed, cycles):
    rng = random.Random(seed)
    source = Requests(ports)
    source.cycle(reset=True)
    for _ in range(cycles):
        source.cycle(offers=rng.randrange(1 << ports), ready=int(rng.randrange(3) != 0),
                     reset=rng.randrange(64) == 0)
    source.drain()
    return source.vectors


def blocked_vectors(ports):
    source = Requests(ports)
    source.cycle(reset=True)
    for _ in range(4 * ports + 1):
        source.cycle(offers=(1 << ports) - 1, ready=0)
    source.cycle(reset=True)
    source.drain()
    return source.vectors


def make_plan(args):
    prefix = f"p{args.ports}"
    baseline = boundary_vectors(args.ports)
    cases = [dict(id=f"{prefix}-boundaries", vectors=baseline,
                  mutation=args.demo_bug, expected_failure=None, category="functional")]
    seeds = range(args.seed, args.seed + (3 if args.profile == "nightly" else 1))
    for seed in seeds:
        cases.append(dict(id=f"{prefix}-random-seed{seed}", seed=seed,
                          vectors=random_vectors(args.ports, seed, args.cycles),
                          mutation=args.demo_bug, expected_failure=None, category="functional"))
    for mutation, label in ((1, "ARB_ONEHOT"), (2, "ARB_STABILITY"), (3, "ARB_ORDER")):
        cases.append(dict(id=f"{prefix}-detect-mutation{mutation}", vectors=baseline,
                          mutation=mutation, expected_failure=label, category="mutation"))
    cases.append(dict(id=f"{prefix}-blocked-sink", vectors=blocked_vectors(args.ports),
                      mutation=0, expected_failure=None, category="diagnostic"))
    for case in cases:
        case["checks"] = len(case["vectors"])
    return cases


def load_catalog(path, ports):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    expanded, ids = [], set()
    for requirement in catalog["requirements"]:
        rid, kind = requirement["id"], requirement["kind"]
        if not isinstance(rid, str) or not rid or rid in ids:
            raise ValueError("duplicate or invalid requirement ID")
        ids.add(rid)
        if kind == "mask-cross":
            goals = [f"mask/{m}/ready{r}" for m in range(1 << ports) for r in (0, 1)]
        elif kind == "per-port":
            goals = [f"serve/port{p}" for p in range(ports)]
        elif kind == "rotation":
            goals = [f"rotate/from{p}/to{(p + 1) % ports}" for p in range(ports)]
        elif kind == "fixed":
            goals = requirement["goals"]
        else:
            raise ValueError("unknown requirement kind")
        if (not isinstance(goals, list) or not goals or len(goals) != len(set(goals)) or
                any(not isinstance(g, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", g) for g in goals)):
            raise ValueError("invalid requirement goals")
        expanded.append(dict(requirement, goals=goals))
    if not expanded:
        raise ValueError("empty requirements")
    return dict(catalog, ports=ports, requirements=expanded), expanded


def parse_metrics(output, ports):
    rows = re.findall(r"^METRICS opportunities=(\d+) accepted=(\d+) blocked=(\d+) max_wall=(\d+) max_service_wait=(\d+) cancelled=(\d+)$", output, re.M)
    services = re.findall(r"^SERVICE port=(\d+) count=(\d+) max_wall=(\d+) max_service_wait=(\d+)$", output, re.M)
    if len(rows) != 1 or len(services) != ports:
        raise ValueError("missing or duplicate arbitration metrics")
    values = list(map(int, rows[0]))
    per_port = [dict(zip(("port", "count", "max_wall", "max_service_wait"), map(int, row))) for row in services]
    if sorted(p["port"] for p in per_port) != list(range(ports)):
        raise ValueError("invalid requester metrics")
    if (values[0] != values[1] or sum(p["count"] for p in per_port) != values[1] or
            values[4] > ports or any(p["max_service_wait"] > ports for p in per_port) or
            max(p["max_wall"] for p in per_port) != values[3] or
            max(p["max_service_wait"] for p in per_port) != values[4]):
        raise ValueError("inconsistent acceptance or wait metrics")
    return dict(zip(("opportunities", "accepted", "blocked", "max_wall", "max_service_wait", "cancelled"), values), per_port=per_port)


def junit(out, args, results, coverage):
    classname = f"arbiter.p{args.ports}"
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
    gate = ET.SubElement(suite, "testcase", name=f"p{args.ports}-requirements-and-coverage",
                         classname=classname + ".gate")
    if not coverage["success"]:
        ET.SubElement(gate, "failure", message="required coverage incomplete").text = ", ".join(coverage["missing"])
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)


def run(args):
    catalog, requirements = load_catalog(args.requirements, args.ports)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases = make_plan(args)
    inputs = [HERE / "rtl/rr_arbiter.sv", HERE / "tb/arbiter_tb.sv", HERE / "run.py",
              SUPPORT_PATH, args.requirements.resolve()]
    write_json(out / "manifest.json", dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        configuration=dict(ports=args.ports), profile=args.profile,
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
        command = [args.iverilog, "-g2012", "-s", "arbiter_tb",
                   f"-Parbiter_tb.PORTS={args.ports}",
                   f"-Parbiter_tb.MUTATION={mutation}", "-o", str(out / f"arbiter-{mutation}.vvp"),
                   str(HERE / "rtl/rr_arbiter.sv"), str(HERE / "tb/arbiter_tb.sv")]
        builds[mutation] = SUPPORT.execute(command, out / f"build-{mutation}.log", args.timeout, out)
    write_json(out / "builds.json", builds)
    results = []
    hits = {}
    for case in cases:
        directory = out / case["id"]
        directory.mkdir()
        vector_path = directory / "vectors.txt"
        vector_path.write_text("".join(f"{rst} {mask:x} {ready}\n" for rst, mask, ready in case["vectors"]), encoding="utf-8")
        log = directory / "simulation.log"
        command = [args.vvp, str(out / f"arbiter-{case['mutation']}.vvp"),
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
        metrics = None
        if status == "pass":
            try:
                metrics = parse_metrics(output, args.ports)
                if case["category"] == "diagnostic" and not (
                        metrics["accepted"] == 0 and metrics["opportunities"] == 0 and
                        metrics["blocked"] > args.ports and metrics["max_wall"] > args.ports):
                    raise ValueError("blocked sink diagnostic did not isolate absence of opportunities")
            except ValueError as exc:
                status, message = "error", str(exc)
        observed = sorted(set(re.findall(r"^COVER (\S+)$", output, re.MULTILINE)))
        # A mutant can demonstrate sensitivity, but cannot complete normal goals.
        credited = observed if status == "pass" and case["category"] == "functional" else []
        for goal in credited:
            hits.setdefault(goal, []).append(case["id"])
        result = dict(id=case["id"], category=case["category"], status=status, message=message,
                      observed_coverage=observed, credited_coverage=credited, metrics=metrics,
                      log=str(log.relative_to(out)), **execution)
        results.append(result)
        write_json(directory / "result.json", result)
        print(f"{status.upper():8} {case['id']}: {message}", flush=True)
    required = {goal for r in requirements for goal in r["goals"]}
    coverage = dict(success=required <= hits.keys(), required=len(required),
                    hit=len(required & hits.keys()), hits=hits,
                    missing=sorted(required - hits.keys()),
                    requirements=[dict(r, passed=set(r["goals"]) <= hits.keys()) for r in requirements])
    complete = [r["id"] for r in results] == [c["id"] for c in cases]
    success = complete and coverage["success"] and all(r["status"] in ("pass", "detected") for r in results)
    write_json(out / "coverage.json", coverage)
    write_json(out / "summary.json", dict(success=success, complete=complete,
                                         planned=len(cases), results=len(results),
                                         functional_pass=sum(r["category"] == "functional" and r["status"] == "pass" for r in results),
                                         mutations_detected=sum(r["status"] == "detected" for r in results),
                                         diagnostics_pass=sum(r["category"] == "diagnostic" and r["status"] == "pass" for r in results),
                                         coverage_hit=coverage["hit"], coverage_required=coverage["required"]))
    junit(out, args, results, coverage)
    print(f"Coverage: {coverage['hit']}/{coverage['required']} required goals")
    print(f"Artifacts: {out}\nRegression: {'PASS' if success else 'FAIL'}")
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ports", type=int, choices=(2, 3, 4), default=3)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--cycles", type=int, help="random cycles per seed (smoke: 200, nightly: 2000)")
    parser.add_argument("--demo-bug", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--requirements", type=Path, default=HERE / "requirements.json")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("arbiter-local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    SUPPORT.resolve_tools(args)
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
