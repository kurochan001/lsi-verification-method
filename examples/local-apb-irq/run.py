#!/usr/bin/env python3
"""APB/interrupt integration regression with cycle-level checking and cross goals."""

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


def transfer(wait, address, write, data=0, event=0):
    return ([[1, 1, 0, write, address, data, 0]] +
            [[1, 1, 1, write, address, data, 0] for _ in range(wait)] +
            [[1, 1, 1, write, address, data, event]])


def boundary_vectors(wait):
    reset = [[0, 0, 0, 0, 0, 0, 0]]
    idle = [1, 0, 0, 0, 0, 0, 0]
    # Store a masked event, unmask it, observe, then acknowledge over APB.
    vectors = reset + [[1, 0, 0, 0, 0, 0, 1]]
    vectors += transfer(wait, 8, 0) + transfer(wait, 0, 1, 1)
    vectors += transfer(wait, 8, 0) + transfer(wait, 8, 1, 1)
    for bit in range(4):
        value = 1 << bit
        for mask in (0, 1):
            for clear in (0, 1):
                for event in (0, 1):
                    vectors += reset + [[1, 0, 0, 0, 0, 0, value]]
                    vectors += transfer(wait, 0, 1, value if mask else 0)
                    vectors += transfer(wait, 8, 1, value if clear else 0,
                                        value if event else 0)
                    vectors += transfer(wait, 8, 0)
    # Mask a source with pending state, without discarding that state.
    vectors += reset + transfer(wait, 0, 1, 15)
    vectors += [[1, 0, 0, 0, 0, 0, 15]] + transfer(wait, 0, 1, 0)
    # Clearing one source must not hide another active source.
    vectors += reset + transfer(wait, 0, 1, 3, event=3)
    vectors += transfer(wait, 8, 1, 1) + transfer(wait, 8, 0)
    vectors += transfer(wait, 8, 1, 2)
    # Upper CONFIG bits do not enable any interrupt source.
    vectors += reset + transfer(wait, 0, 1, 0xfffffff0, event=15)
    # Mask changes and events on the same completion edge.
    vectors += reset + transfer(wait, 0, 1, 1, event=1)
    vectors += reset + transfer(wait, 0, 1, 1) + transfer(wait, 0, 1, 0, event=1)
    # Event storage continues in SETUP and stalls, and during an error response.
    vectors += reset
    phase_events = transfer(wait, 0, 1, 15)
    phase_events[0][-1] = 2
    if wait:
        phase_events[1][-1] = 4
    vectors += phase_events
    vectors += transfer(wait, 16, 1, 0xffffffff, event=8) + transfer(wait, 8, 0)
    # Reset an asserted interrupt, then accept a new event after recovery.
    vectors += reset + transfer(wait, 0, 1, 1, event=1) + reset
    vectors += transfer(wait, 0, 1, 1, event=1) + transfer(wait, 8, 0)
    vectors += [idle]
    return vectors


def random_vectors(wait, seed, transactions):
    # --transactions is the number of random transactions, not bus clock cycles.
    rng = random.Random(seed)
    vectors = [[0, 0, 0, 0, 0, 0, 0]]
    for _ in range(transactions):
        if rng.randrange(12) == 0:
            vectors += [[0, 0, 0, 0, 0, 0, 0]]
        if rng.randrange(3) == 0:
            vectors += [[1, 0, 0, 0, 0, 0, rng.randrange(16)]]
        transaction = transfer(wait, rng.choice((0, 4, 8, 16, 1)), rng.randrange(2),
                               rng.choice((0, 0xffffffff, 0x55555555, rng.getrandbits(32))))
        for row in transaction:
            row[-1] = rng.randrange(16) if rng.randrange(3) == 0 else 0
        vectors += transaction
    vectors += transfer(wait, 0, 0) + transfer(wait, 8, 0)
    vectors += [[1, 0, 0, 0, 0, 0, 0]]
    return vectors


def make_plan(args):
    prefix = f"wait{args.wait}"
    baseline = boundary_vectors(args.wait)
    cases = [dict(id=f"{prefix}-boundaries", vectors=baseline,
                  mutation=args.demo_bug, expected_failure=None, category="functional")]
    for seed in range(args.seed, args.seed + (3 if args.profile == "nightly" else 1)):
        cases.append(dict(id=f"{prefix}-random-seed{seed}", seed=seed,
                          vectors=random_vectors(args.wait, seed, args.transactions),
                          mutation=args.demo_bug, expected_failure=None, category="functional"))
    for mutation, label in ((1, "APB_IRQ_PENDING"), (2, "APB_IRQ_OUTPUT"), (3, "APB_IRQ_RELEASE")):
        cases.append(dict(id=f"{prefix}-detect-mutation{mutation}", vectors=baseline,
                          mutation=mutation, expected_failure=label, category="mutation"))
    for case in cases:
        case["checks"] = len(case["vectors"])
    return cases


def load_catalog(path, wait):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    requirements = catalog["requirements"]
    if not requirements:
        raise ValueError("requirements must be nonempty")
    ids = set()
    for requirement in requirements:
        rid = requirement["id"]
        goals = requirement["goals"]
        minimum = requirement.get("minimum_wait", 0)
        if (not isinstance(rid, str) or not rid or rid in ids or
                not isinstance(goals, list) or not goals or
                any(not isinstance(g, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", g) for g in goals) or
                len(goals) != len(set(goals)) or type(minimum) is not int or minimum < 0):
            raise ValueError("invalid/duplicate requirement ID, goals or minimum_wait")
        ids.add(rid)
    applicable = [r for r in requirements if wait >= r.get("minimum_wait", 0)]
    if not applicable:
        raise ValueError("no applicable requirements")
    excluded = [dict(id=r["id"], reason=f"wait {wait} < minimum_wait {r['minimum_wait']}")
                for r in requirements if r not in applicable]
    return catalog, applicable, excluded


def junit(out, args, results, coverage):
    classname = f"apb_irq.wait{args.wait}"
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
    gate = ET.SubElement(suite, "testcase", name=f"wait{args.wait}-requirements-and-coverage",
                         classname=classname + ".gate")
    if not coverage["success"]:
        ET.SubElement(gate, "failure", message="required coverage incomplete").text = ", ".join(coverage["missing"])
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)


def run(args):
    catalog, requirements, excluded = load_catalog(args.requirements, args.wait)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases = make_plan(args)
    inputs = [HERE / "rtl/apb_irq.sv", HERE.parent / "local-apb/rtl/apb_regs.sv",
              HERE / "tb/apb_irq_tb.sv", HERE / "run.py",
              SUPPORT_PATH, args.requirements.resolve()]
    write_json(out / "manifest.json", dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        configuration=dict(wait_cycles=args.wait), profile=args.profile,
        seed=args.seed, random_transactions=args.transactions, demo_bug=args.demo_bug,
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
        command = [args.iverilog, "-g2012", "-s", "apb_irq_tb",
                   f"-Papb_irq_tb.WAIT_CYCLES={args.wait}",
                   f"-Papb_irq_tb.MUTATION={mutation}", "-o", str(out / f"apb-irq-{mutation}.vvp"),
                   str(HERE.parent / "local-apb/rtl/apb_regs.sv"),
                   str(HERE / "rtl/apb_irq.sv"), str(HERE / "tb/apb_irq_tb.sv")]
        builds[mutation] = SUPPORT.execute(command, out / f"build-{mutation}.log", args.timeout, out)
    write_json(out / "builds.json", builds)
    results = []
    hits = {}
    for case in cases:
        directory = out / case["id"]
        directory.mkdir()
        vector_path = directory / "vectors.txt"
        vector_path.write_text("".join(f"{rst} {sel} {enable} {write} {addr:x} {data:x} {event:x}\n"
                                      for rst, sel, enable, write, addr, data, event in case["vectors"]), encoding="utf-8")
        log = directory / "simulation.log"
        command = [args.vvp, str(out / f"apb-irq-{case['mutation']}.vvp"),
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
    parser.add_argument("--wait", type=int, choices=(0, 1, 3), default=1)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--transactions", type=int, help="random transactions per seed (smoke: 200, nightly: 2000)")
    parser.add_argument("--demo-bug", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--requirements", type=Path, default=HERE / "requirements.json")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("apb-irq-local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    SUPPORT.resolve_tools(args)
    if args.transactions is None:
        args.transactions = 2000 if args.profile == "nightly" else 200
    if os.name != "posix" or args.seed < 0 or not 1 <= args.transactions <= 10000 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("requires POSIX, nonnegative seed, 1..10000 transactions and a finite positive timeout")
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
