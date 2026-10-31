#!/usr/bin/env python3
"""APB/UART/interrupt integration regression with cycle checking and real serial events."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
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


STIM_SPEC = importlib.util.spec_from_file_location("apb_uart_stimulus", HERE / "stimulus.py")
STIM = importlib.util.module_from_spec(STIM_SPEC)
STIM_SPEC.loader.exec_module(STIM)
boundary_vectors = STIM.boundary_vectors
random_vectors = STIM.random_vectors


def make_plan(args):
    prefix = f"wait{args.wait}-parity{args.parity}"
    baseline = boundary_vectors(args.wait, args.parity)
    cases = [dict(id=f"{prefix}-boundaries", vectors=baseline,
                  mutation=args.demo_bug, expected_failure=None, category="functional")]
    for seed in range(args.seed, args.seed + (3 if args.profile == "nightly" else 1)):
        cases.append(dict(id=f"{prefix}-random-seed{seed}", seed=seed,
                          vectors=random_vectors(args.wait, args.parity, seed, args.operations),
                          mutation=args.demo_bug, expected_failure=None, category="functional"))
    for mutation, label in ((1, "APBUART_PENDING"), (2, "APBUART_IRQ"),
                            (3, "APBUART_PENDING"), (4, "APBUART_TX_DATA"), (5, "APBUART_RX_DATA")):
        cases.append(dict(id=f"{prefix}-detect-mutation{mutation}", vectors=baseline,
                          mutation=mutation, expected_failure=label, category="mutation"))
    for case in cases:
        case["checks"] = len(case["vectors"])
        case["metrics"] = STIM.expected_metrics(case["vectors"], args.wait, args.parity)
    return cases


def load_catalog(path, wait, parity):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    requirements = catalog["requirements"]
    if not requirements:
        raise ValueError("requirements must be nonempty")
    ids = set()
    for requirement in requirements:
        rid = requirement["id"]
        goals = requirement["goals"]
        needs_parity = requirement.get("requires_parity", False)
        if (not isinstance(rid, str) or not rid or rid in ids or not isinstance(goals, list) or not goals or
                any(not isinstance(g, str) or not re.fullmatch(r"[A-Za-z0-9_./-]+", g) for g in goals) or
                len(goals) != len(set(goals)) or type(needs_parity) is not bool or
                type(requirement.get("minimum_wait", 0)) is not int or requirement.get("minimum_wait", 0) < 0):
            raise ValueError("invalid requirement ID, goals or applicability condition")
        ids.add(rid)
    applicable = [r for r in requirements if (parity != 0 or not r.get("requires_parity", False)) and wait >= r.get("minimum_wait", 0)]
    if not applicable:
        raise ValueError("no applicable requirements")
    excluded = [dict(id=r["id"], reason="parity disabled" if r.get("requires_parity", False) and not parity else "no wait states") for r in requirements if r not in applicable]
    return catalog, applicable, excluded


def junit(out, args, results, coverage):
    classname = f"apb_uart.wait{args.wait}.parity{args.parity}"
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
    gate = ET.SubElement(suite, "testcase", name=f"wait{args.wait}-parity{args.parity}-requirements-and-coverage",
                         classname=classname + ".gate")
    if not coverage["success"]:
        ET.SubElement(gate, "failure", message="required coverage incomplete").text = ", ".join(coverage["missing"])
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)


def run(args):
    catalog, requirements, excluded = load_catalog(args.requirements, args.wait, args.parity)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases = make_plan(args)
    inputs = [HERE / "rtl/apb_uart.sv", HERE.parent / "local-uart/rtl/uart.sv",
              HERE / "tb/apb_uart_tb.sv", HERE / "run.py", HERE / "stimulus.py",
              SUPPORT_PATH, args.requirements.resolve()]
    write_json(out / "manifest.json", dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        configuration=dict(wait_cycles=args.wait, divisor=STIM.DIVISOR, parity=args.parity), profile=args.profile,
        seed=args.seed, random_operations=args.operations, demo_bug=args.demo_bug,
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
        command = [args.iverilog, "-g2012", "-s", "apb_uart_tb",
                   f"-Papb_uart_tb.WAIT_CYCLES={args.wait}", f"-Papb_uart_tb.PARITY={args.parity}",
                   f"-Papb_uart_tb.MUTATION={mutation}", "-o", str(out / f"apb-uart-{mutation}.vvp"),
                   str(HERE.parent / "local-uart/rtl/uart.sv"), str(HERE / "rtl/apb_uart.sv"), str(HERE / "tb/apb_uart_tb.sv")]
        builds[mutation] = SUPPORT.execute(command, out / f"build-{mutation}.log", args.timeout, out)
    write_json(out / "builds.json", builds)
    results = []
    hits = {}
    for case in cases:
        directory = out / case["id"]
        directory.mkdir()
        vector_path = directory / "vectors.txt"
        vector_path.write_text("".join(f"{rst} {sel} {enable} {write} {addr:x} {data:x} {rxd} {rx} {value:x} {pe} {fe}\n"
                                      for rst, sel, enable, write, addr, data, rxd, rx, value, pe, fe in case["vectors"]), encoding="utf-8")
        log = directory / "simulation.log"
        command = [args.vvp, str(out / f"apb-uart-{case['mutation']}.vvp"),
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
            rows = re.findall(r"^METRICS tx_completed=(\d+) rx_captured=(\d+) rx_reads=(\d+) apb_completed=(\d+) apb_errors=(\d+)$", output, re.M)
            if len(rows) != 1:
                status, message = "error", "missing APB/UART completion metrics"
            else:
                metrics = dict(zip(("tx_completed", "rx_captured", "rx_reads", "apb_completed", "apb_errors"), map(int, rows[0])))
                if any(metrics[k] != n for k, n in case["metrics"].items()):
                    status, message = "error", "APB/UART completion counts disagree"
                else:
                    message = f"{case['checks']} checked cycles"
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
    parser.add_argument("--parity", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--operations", type=int, help="random scenario blocks per seed (smoke: 16, nightly: 128)")
    parser.add_argument("--demo-bug", type=int, choices=(0, 1, 2, 3, 4, 5), default=0)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--requirements", type=Path, default=HERE / "requirements.json")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("apb-uart-local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    SUPPORT.resolve_tools(args)
    if args.operations is None:
        args.operations = 128 if args.profile == "nightly" else 16
    if os.name != "posix" or args.seed < 0 or not 1 <= args.operations <= 1000 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("requires POSIX, nonnegative seed, 1..1000 operations and a finite positive timeout")
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
