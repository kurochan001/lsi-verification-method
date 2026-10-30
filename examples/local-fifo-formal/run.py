#!/usr/bin/env python3
"""Run bounded checks, control proofs, covers and negative formal self-checks."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUPPORT_PATH = HERE.parent / "local-irq-cdc/run.py"
SPEC = importlib.util.spec_from_file_location("formal_process_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)
write_json = SUPPORT.write_json
CONTROL = {"ap_count", "ap_bounds", "ap_flags", "ap_read_valid", "ap_reset", "ap_hold"}
COVERS = {"cp_empty", "cp_full", "cp_simultaneous", "cp_reset_pending", "cp_recovery", "cp_wrap"}


def plan(demo_bug):
    cases = [
        dict(id="control-proof", mode="prove", data=0, mutation=demo_bug, lock=0, expect="PASS"),
        dict(id="data-bmc", mode="bmc", data=1, mutation=demo_bug, lock=0, expect="PASS"),
        dict(id="scenario-cover", mode="cover", data=1, mutation=0, lock=0, expect="PASS"),
    ]
    for mutation, label in ((1, "ap_data"), (2, "ap_count"), (3, "ap_reset")):
        cases.append(dict(id=f"detect-mutation{mutation}", mode="bmc", data=1,
                          mutation=mutation, lock=0, expect="FAIL", failure=label))
    cases.extend([
        dict(id="overconstrained-proof", mode="prove", data=0, mutation=0, lock=1, expect="PASS"),
        dict(id="detect-overconstraint", mode="cover", data=0, mutation=0, lock=1, expect="FAIL"),
    ])
    return cases


def inspect_model(path, case):
    """Audit the named properties and assumptions actually read by pinned Yosys."""
    model = json.loads(path.read_text())
    properties = {"assert": set(), "assume": set(), "cover": set()}
    for module in model["modules"]:
        for group in module.get("cell_sorts", []):
            if group["type"] == "$check":
                for cell in group["cells"]:
                    flavor = cell["parameters"]["FLAVOR"]
                    if flavor in properties:
                        properties[flavor].add(cell["name"])
    expected = dict(assertions=CONTROL | ({"ap_data"} if case["data"] else set()),
                    assumptions={"as_initial_reset"} | ({"as_lock_reset"} if case["lock"] else set()))
    if (properties["assert"] != expected["assertions"] or
            properties["assume"] != expected["assumptions"] or properties["cover"] != COVERS):
        raise ValueError("compiled property/assumption inventory differs from the fixed plan")
    return {key: sorted(value) for key, value in properties.items()}


def judge(case, execution, status, log, traces):
    """FAIL is useful only when the planned diagnostic has concrete evidence."""
    if execution["error"]:
        return "error", execution["error"]
    if status not in ("PASS", "FAIL"):
        return "error", f"formal task incomplete or invalid: {status}"
    if execution["returncode"] != (0 if status == "PASS" else 2):
        return "error", "status and SBY exit code disagree"
    if status != case["expect"]:
        return "fail", f"expected {case['expect']}, got {status}"
    failed = set(re.findall(r"Assert failed in fifo_formal: (\w+)", log))
    reached = set(re.findall(r"Reached cover statement in step \d+ at fifo_formal: (\w+)", log))
    unreached = set(re.findall(r"Unreached cover statement at fifo_formal: (\w+)", log))
    if status == "PASS":
        if failed:
            return "error", "PASS log contains a failed assertion"
        if case["mode"] == "prove" and "successful proof by k-induction" not in log:
            return "error", "missing completed induction proof"
        if case["mode"] == "cover" and (reached != COVERS or unreached or not traces):
            return "error", "cover targets or witness traces missing"
        if case["lock"]:
            return "pass", "diagnostic proof holds only under the deliberately permanent-reset assumption"
        return "pass", "control safety proven" if case["mode"] == "prove" else (
            "all six cover goals reached" if case["mode"] == "cover" else "no counterexample within depth 10")
    if case.get("failure"):
        if case["failure"] in failed and failed <= CONTROL | {"ap_data"} and traces:
            return "detected", f"counterexample confirms {case['failure']}"
        return "error", "FAIL lacks the intended assertion and counterexample trace"
    if case["lock"] and case["mode"] == "cover" and unreached == COVERS and not reached and not failed and not traces:
        return "detected", "all six goals blocked by the deliberately permanent-reset assumption"
    return "error", "unexplained FAIL"


def run(args):
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cases = plan(args.demo_bug)
    inputs = [HERE / "fifo_formal.sv", HERE / "fifo.sby.in", HERE / "run.py",
              HERE / "tools-requirements.txt", SUPPORT_PATH,
              HERE.parent / "local-fifo/rtl/sync_fifo.sv"]
    versions = {}
    for package in ("yowasp-yosys", "yowasp-runtime", "wasmtime", "platformdirs", "click", "z3-solver"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed in runner Python environment"
    write_json(out / "manifest.json", dict(
        schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        depth=args.depth, width=8, formal_depth=10, python=sys.version,
        timeout_seconds=args.timeout, tool_packages=versions, cases=cases,
        source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}))
    probes = {}
    for name, command in (("yosys", [args.yosys, "-V"]), ("sby", [args.sby, "--version"]), ("z3", ["z3", "--version"])):
        log = out / f"{name}-version.log"
        probes[name] = SUPPORT.execute(command, log, args.timeout, out)
    write_json(out / "tools.json", dict(packages=versions, probes=probes))
    results = []
    for case in cases:
        directory = out / case["id"]
        directory.mkdir()
        shutil.copy2(HERE / "fifo_formal.sv", directory / "fifo_formal.sv")
        shutil.copy2(HERE.parent / "local-fifo/rtl/sync_fifo.sv", directory / "sync_fifo.sv")
        config = (HERE / "fifo.sby.in").read_text()
        values = dict(MODE=case["mode"], DEPTH=args.depth, MUTATION=case["mutation"],
                      CHECK_DATA=case["data"], LOCK_RESET=case["lock"],
                      COVER_OPTIONS="cover_assert on" if case["mode"] == "cover" else "")
        for key, value in values.items():
            config = config.replace("@" + key + "@", str(value))
        (directory / "fifo.sby").write_text(config)
        command = [args.sby, "--yosys", args.yosys, "--smtbmc", args.smtbmc,
                   "--witness", args.witness, "fifo.sby"]
        execution = SUPPORT.execute(command, directory / "console.log", args.timeout, directory)
        work = directory / "fifo"
        status_file = work / "status"
        status = status_file.read_text().split()[0] if status_file.is_file() and status_file.read_text().strip() else "MISSING"
        log_file = work / "logfile.txt"
        log = log_file.read_text(errors="replace") if log_file.is_file() else ""
        traces = sorted(str(p.relative_to(out)) for p in (work / "engine_0").glob("*.vcd") if p.stat().st_size)
        inventory = None
        try:
            if execution["error"] or status not in ("PASS", "FAIL"):
                outcome, message = judge(case, execution, status, log, traces)
            else:
                inventory = inspect_model(work / "model/design.json", case)
                outcome, message = judge(case, execution, status, log, traces)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            outcome, message = "error", f"invalid formal evidence: {exc}"
        result = dict(id=f"d{args.depth}-{case['id']}", outcome=outcome, message=message,
                      formal_status=status, inventory=inventory, traces=traces, **execution)
        results.append(result)
        write_json(directory / "result.json", result)
        print(f"{outcome.upper():8} {result['id']}: {message}", flush=True)
    success = len(results) == len(cases) and all(r["outcome"] in ("pass", "detected") for r in results)
    write_json(out / "summary.json", dict(success=success, planned=len(cases), results=results,
                                         explanation="Data is bounded only; diagnostic PASS/FAIL does not expand the normal proof scope."))
    suite = ET.Element("testsuite", name=f"formal.d{args.depth}", tests=str(len(results)),
                       failures=str(sum(r["outcome"] == "fail" for r in results)),
                       errors=str(sum(r["outcome"] == "error" for r in results)))
    for result in results:
        node = ET.SubElement(suite, "testcase", name=result["id"], classname=f"formal.d{args.depth}", time=f"{result['seconds']:.6f}")
        if result["outcome"] in ("fail", "error"):
            ET.SubElement(node, "failure" if result["outcome"] == "fail" else "error", message=result["message"])
        ET.SubElement(node, "system-out").text = f"SBY={result['formal_status']}; {result['message']}"
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)
    print(f"Artifacts: {out}\nFormal regression: {'PASS' if success else 'FAIL'}")
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, choices=(1, 3), default=3)
    parser.add_argument("--demo-bug", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--sby", default="yowasp-sby")
    parser.add_argument("--yosys", default="yowasp-yosys")
    parser.add_argument("--smtbmc", default="yowasp-yosys-smtbmc")
    parser.add_argument("--witness", default="yowasp-yosys-witness")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("formal-local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    if os.name != "posix" or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("requires POSIX and a finite positive timeout")
    if args.out.exists():
        parser.error("output directory already exists; choose a new --out")
    previous = signal.signal(signal.SIGTERM, SUPPORT.interrupted)
    try:
        return run(args)
    except SUPPORT.RunInterrupted as exc:
        return 128 + exc.signum
    except KeyboardInterrupt:
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    sys.exit(main())
