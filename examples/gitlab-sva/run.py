#!/usr/bin/env python3
"""Execute real SVA assertions and reconcile native Verilator cover counters."""
import argparse
from collections import Counter
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
SPEC = importlib.util.spec_from_file_location("sva_process_support", SUPPORT_PATH)
SUPPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPPORT)
write_json = SUPPORT.write_json

# This example has a fixed checker and six corresponding sensitivity cases.
# Keep the requirement bindings in the same reviewed plan as those cases.
ASSERTION_COVERS = {
    "ap_set_wins": {"cp_set_wins_seen", "cp_set_wins_done"},
    "ap_set_only": {"cp_set_only_seen", "cp_set_only_done"},
    "ap_clear_only": {"cp_clear_only_seen", "cp_clear_only_done"},
    "ap_hold": {"cp_hold_seen", "cp_hold_done"},
    "ap_reset": {"cp_reset_pending_seen", "cp_reset_done"},
    "ap_irq": {"cp_masked_pending", "cp_unmasked_pending"},
}


def boundary_vectors():
    # Final idle clock observes the last obligation without starting a new one.
    return [[0, 0, 0, 0, 0], [1, 1, 0, 0, 0], [1, 0, 0, 0, 0],
            [1, 1, 1, 0, 0], [1, 0, 0, 0, 0], [1, 0, 1, 0, 0],
            [1, 0, 0, 0, 0], [1, 1, 0, 1, 0], [1, 0, 0, 1, 0],
            [0, 0, 0, 1, 0], [1, 0, 0, 1, 0], [1, 0, 0, 1, 0]]


def random_vectors(seed, cycles):
    rng = random.Random(seed)
    return ([[0, 0, 0, 0, 0]] +
            [[int(rng.randrange(24) != 0), rng.randrange(2), rng.randrange(2), rng.randrange(2), 0]
             for _ in range(cycles)] + [[1, 0, 0, 0, 0]])


def make_plan(args):
    cases = [dict(id="sva-boundaries", category="functional", vectors=boundary_vectors(),
                  mutation=args.demo_bug, selftest=0, expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == "nightly" else 1)):
        cases.append(dict(id=f"sva-random-seed{seed}", category="functional", seed=seed,
                          vectors=random_vectors(seed, args.cycles), mutation=args.demo_bug,
                          selftest=0, expected_failure=None))
    for mutation, label in ((1, "IRQ_SET_WINS"), (2, "IRQ_SET_ONLY"), (3, "IRQ_RESET")):
        cases.append(dict(id=f"detect-rtl-mutation{mutation}", category="mutation",
                          vectors=boundary_vectors(), mutation=mutation, selftest=0,
                          expected_failure=label))
    fixtures = (
        (1, "IRQ_CLEAR_ONLY", [[0, 0, 0, 0, 0], [1, 1, 0, 0, 0],
                               [1, 0, 1, 0, 0], [1, 0, 0, 0, 1], [1, 0, 0, 0, 0]]),
        (2, "IRQ_HOLD", [[0, 0, 0, 0, 0], [1, 0, 0, 0, 0],
                         [1, 0, 0, 0, 1], [1, 0, 0, 0, 0]]),
        (3, "IRQ_OUTPUT", [[0, 0, 0, 0, 0], [1, 0, 0, 0, 1], [1, 0, 0, 0, 0]]),
    )
    for mode, label, vectors in fixtures:
        cases.append(dict(id=f"detect-checker-fault{mode}", category="checker-selftest",
                          vectors=vectors, mutation=0, selftest=mode, expected_failure=label))
    cases.append(dict(id="diagnose-vacuous-stimulus", category="diagnostic", mutation=0,
                      selftest=0, expected_failure=None,
                      vectors=[[0, 0, 0, 0, 0]] + [[1, 0, 0, 0, 0] for _ in range(4)]))
    for case in cases:
        case["checks"] = len(case["vectors"])
    return cases


def load_catalog(path):
    catalog = json.loads(path.read_text(encoding="utf-8"))
    requirements = catalog["requirements"]
    ids, goals, assertions = set(), set(), set()
    if not requirements:
        raise ValueError("empty requirements")
    for requirement in requirements:
        rid, assertion, covers = requirement["id"], requirement["assertion"], requirement["goals"]
        if (not isinstance(rid, str) or not rid or rid in ids or
                not isinstance(assertion, str) or not re.fullmatch(r"ap_\w+", assertion) or
                not isinstance(covers, list) or not covers or len(covers) != len(set(covers)) or
                any(not isinstance(c, str) or not re.fullmatch(r"cp_\w+", c) or c in goals for c in covers)):
            raise ValueError("invalid or duplicate requirement/assertion/cover")
        if assertion not in ASSERTION_COVERS or assertion in assertions:
            raise ValueError("unknown or duplicate assertion in requirements")
        if set(covers) != ASSERTION_COVERS[assertion]:
            raise ValueError("requirement covers do not match their assertion")
        ids.add(rid)
        assertions.add(assertion)
        goals.update(covers)
    if assertions != ASSERTION_COVERS.keys():
        raise ValueError("requirements omit a planned assertion")
    return catalog, goals


def native_counts(path, labels, checker_source=HERE / "irq_checker.sv"):
    """Read native coverage, requiring one known user counter per cover label."""
    counts = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"C '([^']*)' (\d+)", line)
        if not match:
            raise ValueError("malformed native coverage record")
        metadata = dict(field.split("\x02", 1) for field in match[1].split("\x01") if field)
        # 5.006 identifies user counters by page; newer versions add t=user.
        legacy_user = "t" not in metadata and metadata.get("page") == "v_user/irq_checker"
        if metadata.get("t") != "user" and not legacy_user:
            continue
        label = metadata.get("o")
        if (label not in labels or label in counts or
                metadata.get("h") != f"TOP.sva_tb.checker_inst.{label}" or
                Path(metadata.get("f", "")).resolve() != checker_source.resolve()):
            raise ValueError("unexpected/duplicate cover or checker instance/source")
        counts[label] = int(match[2])
    if counts.keys() != labels:
        raise ValueError("missing native cover instrumentation")
    return counts


def classify(case, execution, output, counts):
    status, message = SUPPORT.classify(case, execution, output)
    if status not in ("pass", "detected"):
        return status, message
    if counts is None:
        return "error", "native coverage unavailable or invalid"
    logged = Counter(re.findall(r"^COVER (\w+)$", output, re.MULTILINE))
    if set(logged) - counts.keys() or any(logged[c] != n for c, n in counts.items()):
        return "error", "cover actions and native counters disagree"
    if case["category"] == "diagnostic":
        expected_hit = {"cp_hold_seen", "cp_hold_done"}
        if {c for c, n in counts.items() if n > 0} != expected_hit:
            return "error", "vacuous diagnostic did not isolate missing antecedents"
        return "pass", "no set/clear antecedent: stimulus insufficiency confirmed"
    return status, message


def junit(out, results, coverage):
    suite = ET.Element("testsuite", name="sva", tests=str(len(results) + 1),
                       failures=str(sum(r["status"] == "fail" for r in results) + int(not coverage["success"])),
                       errors=str(sum(r["status"] == "error" for r in results)))
    for result in results:
        case = ET.SubElement(suite, "testcase", name=result["id"],
                             classname="sva." + result["category"], time=f"{result['seconds']:.6f}")
        if result["status"] in ("fail", "error"):
            ET.SubElement(case, "failure" if result["status"] == "fail" else "error",
                          message=result["message"]).text = result["log"]
    gate = ET.SubElement(suite, "testcase", name="sva-requirements-and-cover", classname="sva.gate")
    if not coverage["success"]:
        ET.SubElement(gate, "failure", message="required native covers incomplete").text = ", ".join(coverage["missing"])
    ET.indent(suite)
    ET.ElementTree(suite).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)


def run(args):
    catalog, labels = load_catalog(args.requirements)
    cases = make_plan(args)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sources = [HERE / "irq_checker.sv", HERE / "sva_tb.sv", HERE / "sim_main.cpp",
               HERE.parent / "gitlab-regression/rtl/irq_pending.sv", SUPPORT_PATH,
               HERE / "run.py", args.requirements.resolve(), HERE / "gitlab-ci.yml", ROOT / ".gitlab-ci.yml"]
    write_json(out / "manifest.json", dict(
        created_at=datetime.now(timezone.utc).isoformat(), schema_version=1,
        profile=args.profile, seed=args.seed, cycles=args.cycles, demo_bug=args.demo_bug,
        checker_off=args.checker_off, tail_observation_cycles=1, python=sys.version,
        ci={k: os.environ.get(k) for k in ("CI_COMMIT_SHA", "CI_PIPELINE_ID", "CI_JOB_ID")},
        source_sha256={str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p):
                       hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}, cases=cases))
    write_json(out / "requirements.json", catalog)
    version = SUPPORT.execute([args.verilator, "--version"], out / "version.log", args.timeout, out)
    write_json(out / "tools.json", dict(verilator=version,
                                       output=(out / "version.log").read_text(errors="replace")))
    command = [args.verilator, "--cc", "--exe", "--build", "-j", "2", "--timing", "--assert",
               "--coverage-user", "--trace", "--top-module", "sva_tb", "--Mdir", str(out / "build"),
               str(HERE.parent / "gitlab-regression/rtl/irq_pending.sv"), str(HERE / "irq_checker.sv"),
               str(HERE / "sva_tb.sv"), str(HERE / "sim_main.cpp")]
    build = SUPPORT.execute(command, out / "build.log", args.build_timeout, out)
    write_json(out / "build.json", build)
    results, hits = [], {}
    for case in cases:
        directory = out / case["id"]
        directory.mkdir()
        vectors = directory / "vectors.txt"
        vectors.write_text("".join(" ".join(map(str, row)) + "\n" for row in case["vectors"]))
        log = directory / "simulation.log"
        command = [str(out / "build/Vsva_tb"), f"+VECTORS={vectors}", f"+CHECKS={case['checks']}",
                   f"+MUTATION={case['mutation']}", f"+SELFTEST={case['selftest']}",
                   f"+CHECKER_OFF={int(args.checker_off)}", f"+WAVE={directory / 'wave.vcd'}"]
        if build["error"] or build["returncode"] != 0:
            execution = dict(command=command, returncode=None, seconds=0, error="build failed; see build.log")
            log.write_text(execution["error"] + "\n")
        else:
            execution = SUPPORT.execute(command, log, args.timeout, directory)
        output = log.read_text(errors="replace")
        counts, audit_error = None, None
        if not execution["error"]:
            try:
                counts = native_counts(directory / "coverage.dat", labels)
            except (OSError, ValueError) as exc:
                audit_error = str(exc)
        status, message = classify(case, execution, output, counts)
        if audit_error and status == "error":
            message += ": " + audit_error
        observed = sorted(c for c, n in (counts or {}).items() if n > 0)
        credited = observed if status == "pass" and case["category"] == "functional" else []
        for label in credited:
            hits.setdefault(label, []).append(case["id"])
        result = dict(id=case["id"], category=case["category"], status=status, message=message,
                      native_counts=counts, observed_coverage=observed, credited_coverage=credited,
                      log=str(log.relative_to(out)), **execution)
        write_json(directory / "result.json", result)
        results.append(result)
        print(f"{status.upper():8} {case['id']}: {message}", flush=True)
    coverage = dict(success=labels <= hits.keys(), required=len(labels), hit=len(labels & hits.keys()),
                    missing=sorted(labels - hits.keys()), hits=hits,
                    requirements=[dict(r, passed=set(r["goals"]) <= hits.keys()) for r in catalog["requirements"]])
    complete = [r["id"] for r in results] == [c["id"] for c in cases]
    success = complete and coverage["success"] and all(r["status"] in ("pass", "detected") for r in results)
    write_json(out / "coverage.json", coverage)
    write_json(out / "summary.json", dict(success=success, complete=complete, planned=len(cases), results=len(results),
                                         functional_pass=sum(r["category"] == "functional" and r["status"] == "pass" for r in results),
                                         sensitivity_detected=sum(r["status"] == "detected" for r in results),
                                         diagnostics_pass=sum(r["category"] == "diagnostic" and r["status"] == "pass" for r in results),
                                         coverage_hit=coverage["hit"], coverage_required=len(labels)))
    junit(out, results, coverage)
    print(f"Coverage: {coverage['hit']}/{len(labels)} native cover goals\nRegression: {'PASS' if success else 'FAIL'}")
    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--cycles", type=int)
    parser.add_argument("--demo-bug", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--checker-off", action="store_true", help="negative demo: disable checker; regression must fail")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--build-timeout", type=float, default=180)
    parser.add_argument("--requirements", type=Path, default=HERE / "requirements.json")
    parser.add_argument("--out", type=Path, default=Path("artifacts") / datetime.now(timezone.utc).strftime("sva-local-%Y%m%dT%H%M%S%fZ"))
    args = parser.parse_args()
    if args.cycles is None:
        args.cycles = 2000 if args.profile == "nightly" else 200
    if (os.name != "posix" or args.seed < 0 or not 1 <= args.cycles <= 10000 or
            any(not math.isfinite(v) or v <= 0 for v in (args.timeout, args.build_timeout))):
        parser.error("requires POSIX, nonnegative seed, 1..10000 cycles and finite positive timeouts")
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
