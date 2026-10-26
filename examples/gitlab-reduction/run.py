#!/usr/bin/env python3
"""Measure full, coverage-selected and stress-preserving RTL regressions."""
import argparse
from datetime import datetime, timezone
from fractions import Fraction
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
SPEC = importlib.util.spec_from_file_location("reduction_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)
write_json = SUPPORT.write_json
STRATEGIES = ("full", "coverage_only", "guarded")
MUTATIONS = {1: ("IRQ_SET_WINS",), 2: ("IRQ_SET_ONLY", "IRQ_SET_WINS"),
             3: ("IRQ_RESET",), 4: ("IRQ_SET_WINS",)}


def atomic_vectors(pending, enabled, op):
    rows = [[0, 0, 0, enabled]]
    if pending:
        rows += [[1, 1, 0, enabled]]
    return rows + [[1, op & 1, (op >> 1) & 1, enabled],
                   [1, 0, 0, enabled], [1, 0, 1, enabled]]


def make_candidates(profile, seed):
    cases = []
    for pending in range(2):
        for enabled in range(2):
            for op in range(4):
                cases.append(dict(id=f"atomic-p{pending}-en{enabled}-op{op}",
                                  vectors=atomic_vectors(pending, enabled, op)))
            cases.append(dict(id=f"combined-p{pending}-en{enabled}", vectors=[
                row for op in range(4) for row in atomic_vectors(pending, enabled, op)]))
    cases.append(dict(id="reset-recovery", vectors=[
        [0, 0, 0, 1], [1, 1, 0, 1], [0, 0, 0, 1],
        [1, 1, 0, 0], [1, 0, 0, 0], [1, 0, 1, 0]]))
    cases.append(dict(id="stress-long-history", vectors=[[0, 0, 0, 1]] +
                      [[1, 1, int(i >= 8), 1] for i in range(12)] + [[1, 0, 1, 1], [1, 0, 0, 1]]))
    for value in range(seed, seed + (4 if profile == "nightly" else 2)):
        rng = random.Random(value)
        rows, streak = [[0, 0, 0, 0]], 0
        for _ in range(128 if profile == "nightly" else 32):
            event = rng.randrange(2) if streak < 4 else 0
            streak = streak + 1 if event else 0
            rows.append([1, event, rng.randrange(2), rng.randrange(2)])
        rows.append([1, 0, 0, 0])
        cases.append(dict(id=f"short-random-seed{value}", seed=value, vectors=rows))
    for case in cases:
        case["checks"] = len(case["vectors"])
    return cases


def load_catalog(path, cases):
    catalog = json.loads(path.read_text())
    ids, goals = set(), set()
    case_ids = [c["id"] for c in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("duplicate candidate ID")
    for requirement in catalog["requirements"]:
        rid, values = requirement["id"], requirement["goals"]
        if (not isinstance(rid, str) or not rid or rid in ids or not values or
                len(values) != len(set(values)) or any(not isinstance(g, str) or not g or g in goals for g in values)):
            raise ValueError("invalid or duplicate requirement/goal")
        ids.add(rid)
        goals.update(values)
    guards = catalog["guard_cases"]
    if not goals or not guards or len(guards) != len(set(guards)) or set(guards) - set(case_ids):
        raise ValueError("missing goals or invalid guard cases")
    return catalog, goals, guards


def greedy_select(observations, required, mandatory=()):
    """Deterministic additional-goals/cycles greedy selection, not a minimum proof."""
    records = {r["id"]: r for r in observations}
    if len(records) != len(observations) or set(mandatory) - records.keys():
        raise ValueError("duplicate observation or absent mandatory case")
    if any(r["status"] != "pass" or type(r["checks"]) is not int or r["checks"] <= 0 for r in observations):
        raise ValueError("selection requires complete passing learning observations")
    selected, covered = set(mandatory), set()
    for cid in selected:
        covered.update(records[cid]["observed_coverage"])
    decisions = []
    while not required <= covered:
        choices = []
        for cid, record in records.items():
            if cid in selected:
                continue
            gain = (set(record["observed_coverage"]) & required) - covered
            if gain:
                choices.append((-Fraction(len(gain), record["checks"]), -len(gain), record["checks"], cid, gain))
        if not choices:
            raise ValueError("learning observations do not cover all required goals")
        _, _, _, cid, gain = min(choices, key=lambda row: row[:4])
        selected.add(cid)
        covered.update(gain)
        decisions.append(dict(id=cid, added_goals=sorted(gain), cost_cycles=records[cid]["checks"]))
    return sorted(selected), decisions


def classify_probe(case, execution, output, labels):
    if execution["error"]:
        return "error", execution["error"]
    failures = re.findall(r"^CHECK_FAIL (\w+)$", output, re.M)
    passes = re.findall(r"^RESULT PASS checks=(\d+)$", output, re.M)
    if execution["returncode"] != 0 and len(failures) == 1 and failures[0] in labels and not passes:
        return "detected", failures[0]
    if execution["returncode"] == 0 and not failures and passes == [str(case["checks"])]:
        return "survived", "no violation in this case"
    return "error", "incomplete run or unrelated failure"


def write_junit(out, gates):
    suite = ET.Element("testsuite", name="reduction", tests=str(len(gates)),
                       failures=str(sum(g["status"] == "fail" for g in gates.values())),
                       errors=str(sum(g["status"] == "error" for g in gates.values())))
    for name, gate in gates.items():
        case = ET.SubElement(suite, "testcase", classname="reduction", name=name)
        if gate["status"] != "pass":
            ET.SubElement(case, "failure" if gate["status"] == "fail" else "error",
                          message=gate["message"])
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)


def run(args):
    cases = make_candidates(args.profile, args.seed)
    catalog, required, guards = load_catalog(args.requirements, cases)
    records = {c["id"]: c for c in cases}
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    names = ["learning", "selection"] + [f"{s}/normal" for s in STRATEGIES] + [
        f"{s}/mutation{m}" for s in STRATEGIES for m in MUTATIONS] + ["comparison"]
    gates = {n: dict(status="error", message="not executed") for n in names}
    sources = [HERE / "run.py", HERE / "rtl/reduction_irq.sv", HERE / "tb/reduction_tb.sv",
               HERE.parent / "gitlab-regression/rtl/irq_pending.sv", SUPPORT_PATH,
               args.requirements.resolve(), HERE / "gitlab-ci.yml", ROOT / ".gitlab-ci.yml"]
    write_json(out / "manifest.json", dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(),
        profile=args.profile, seed=args.seed, demo_bug=args.demo_bug, omit_guard=args.omit_guard,
        python=sys.version, candidates=cases, required=sorted(required), guard_cases=guards,
        sensitivity=dict(known=[1, 2, 3], additional=[4], expected_labels=MUTATIONS),
        ci={k: os.environ.get(k) for k in ("CI_COMMIT_SHA", "CI_PIPELINE_ID", "CI_JOB_ID")},
        source_sha256={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):
                       hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}))
    write_json(out / "requirements.json", catalog)
    tools = {}
    for name, command in (("iverilog", [args.iverilog, "-V"]), ("vvp", [args.vvp, "-V"])):
        log = out / f"{name}-version.log"
        execution = SUPPORT.execute(command, log, args.timeout, out)
        tools[name] = dict(execution, output=log.read_text(errors="replace"))
    write_json(out / "tools.json", tools)
    builds = {}
    for mutation in range(5):
        command = [args.iverilog, "-g2012", "-s", "reduction_tb", f"-Preduction_tb.MUTATION={mutation}",
                   "-o", str(out / f"model-{mutation}.vvp"),
                   str(HERE.parent / "gitlab-regression/rtl/irq_pending.sv"),
                   str(HERE / "rtl/reduction_irq.sv"), str(HERE / "tb/reduction_tb.sv")]
        builds[mutation] = SUPPORT.execute(command, out / f"build-{mutation}.log", args.timeout, out)
    write_json(out / "builds.json", builds)
    all_runs = []

    def simulate(case, mutation, phase):
        directory = out / phase / case["id"]
        directory.mkdir(parents=True)
        path = directory / "vectors.txt"
        path.write_text("".join(" ".join(map(str, row)) + "\n" for row in case["vectors"]))
        log = directory / "simulation.log"
        command = [args.vvp, str(out / f"model-{mutation}.vvp"), f"+VECTORS={path}"]
        build = builds[mutation]
        if build["error"] or build["returncode"] != 0:
            execution = dict(command=command, returncode=None, seconds=0, error="build failed")
            log.write_text("build failed\n")
        else:
            execution = SUPPORT.execute(command, log, args.timeout, directory)
        output = log.read_text(errors="replace")
        if phase.startswith("learning") or phase.endswith("normal"):
            status, message = SUPPORT.classify(dict(case, expected_failure=None), execution, output)
        else:
            status, message = classify_probe(case, execution, output, MUTATIONS[mutation])
        observations = sorted(set(re.findall(r"^COVER (\S+)$", output, re.M)))
        cycle_match = re.search(r"cycle=(\d+)", output)
        executed_cycles = case["checks"] if status in ("pass", "survived") else (
            int(cycle_match[1]) if status == "detected" and cycle_match else None)
        result = dict(id=case["id"], phase=phase, mutation=mutation, status=status, message=message,
                      checks=case["checks"], executed_cycles=executed_cycles,
                      observed_coverage=observations if status == "pass" else [],
                      log=str(log.relative_to(out)), **execution)
        write_json(directory / "result.json", result)
        all_runs.append(result)
        return result

    def finish(summary):
        summary.update(success=all(g["status"] == "pass" for g in gates.values()),
                       profile=args.profile, candidate_cases=len(cases), simulations=len(all_runs),
                       build_seconds=sum(b["seconds"] for b in builds.values()), gates=gates)
        write_json(out / "runs.json", all_runs)
        write_json(out / "summary.json", summary)
        write_junit(out, gates)
        print(f"Regression: {'PASS' if summary['success'] else 'FAIL'}; artifacts: {out}")
        return 0 if summary["success"] else 1

    learning = [simulate(c, args.demo_bug, "learning") for c in cases]
    learned = {g for r in learning if r["status"] == "pass" for g in r["observed_coverage"]}
    learning_ok = all(r["status"] == "pass" for r in learning) and required <= learned
    gates["learning"] = dict(status="pass" if learning_ok else "fail", message="complete passing learning suite required")
    if not learning_ok:
        return finish(dict(reason="learning failed; selection and validation were not run"))
    selected, decisions = greedy_select(learning, required)
    guarded, guarded_decisions = greedy_select(learning, required, () if args.omit_guard else guards)
    strategies = dict(full=sorted(records), coverage_only=selected, guarded=guarded)
    selection_ok = set(guards) <= set(guarded) and all(set(ids) <= records.keys() for ids in strategies.values())
    gates["selection"] = dict(status="pass" if selection_ok else "fail", message="valid IDs and mandatory stress retained")
    write_json(out / "selection.json", dict(strategies=strategies, decisions=decisions,
               guarded_decisions=guarded_decisions, cost="planned clock cycles", algorithm="greedy additional goals / cycles"))
    measurements = {}
    for strategy, ids in strategies.items():
        # Fresh executions; learning observations are never validation evidence.
        normal = [simulate(records[cid], args.demo_bug, f"{strategy}/normal") for cid in ids]
        hits = {g for r in normal if r["status"] == "pass" for g in r["observed_coverage"]}
        ok = all(r["status"] == "pass" for r in normal) and required <= hits
        gates[f"{strategy}/normal"] = dict(status="pass" if ok else "fail", message="fresh normal execution and required goals")
        probes = {}
        for mutation in MUTATIONS:
            results = [simulate(records[cid], mutation, f"{strategy}/mutation{mutation}") for cid in ids]
            detected = [r["id"] for r in results if r["status"] == "detected"]
            valid = all(r["status"] in ("detected", "survived") for r in results)
            # Counterexample demonstration: coverage-only intentionally misses M4.
            expected_detection = mutation != 4 or strategy != "coverage_only"
            ok = valid and bool(detected) == expected_detection
            gates[f"{strategy}/mutation{mutation}"] = dict(status="pass" if ok else "fail",
                message="known defects retained" if mutation != 4 else "history-dependent evaluation defect compared")
            probes[str(mutation)] = dict(detected=bool(detected), detected_by=detected,
                                         expected_detection=expected_detection, valid=valid,
                                         executed_cycles=sum(r["executed_cycles"] or 0 for r in results),
                                         simulation_seconds=sum(r["seconds"] for r in results))
        measurements[strategy] = dict(cases=len(ids), case_ids=ids,
            cycles=sum(r["executed_cycles"] or 0 for r in normal),
            simulation_seconds=sum(r["seconds"] for r in normal),
            coverage_required=len(required), coverage_hit=len(required & hits), missing=sorted(required - hits),
            additional_history_observed=catalog["additional_observation"] in hits, probes=probes)
        print(f"{strategy}: {len(ids)} cases, {measurements[strategy]['cycles']} cycles, "
              f"{len(required & hits)}/{len(required)} goals, M4 detected={probes['4']['detected']}")
    full_cycles = measurements["full"]["cycles"]
    comparison_ok = all(measurements[s]["cycles"] < full_cycles for s in ("coverage_only", "guarded"))
    gates["comparison"] = dict(status="pass" if comparison_ok else "fail", message="both selections reduce normal cycles")
    return finish(dict(measurements=measurements,
                       learning_cycles=sum(r["executed_cycles"] or 0 for r in learning),
                       learning_simulation_seconds=sum(r["seconds"] for r in learning)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--demo-bug", type=int, choices=range(5), default=0)
    parser.add_argument("--omit-guard", action="store_true", help="negative demo: remove mandatory stress retention")
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--requirements", type=Path, default=HERE / "requirements.json")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("reduction-local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    if os.name != "posix" or args.seed < 0 or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("requires POSIX, nonnegative seed and a finite positive timeout")
    if args.out.exists():
        parser.error("output directory already exists")
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
