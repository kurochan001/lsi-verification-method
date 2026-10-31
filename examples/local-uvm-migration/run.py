#!/usr/bin/env python3
"""Replay identical APB vectors through legacy and native passive-UVM environments."""
from bisect import bisect_right
from collections import Counter
import hashlib
import importlib.util
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


E = load("migration_evidence", HERE.parent / "local-exploration-common/evidence.py")
LEGACY = load("migration_legacy", HERE.parent / "local-apb/run.py")
BASE = HERE.parent / "local-uvm"
SOURCES = [BASE / "tb/apb_if.sv", HERE / "tb/replay_control_if.sv",
           BASE / "tb/uvm_apb_pkg.sv", HERE / "tb/migration_pkg.sv",
           HERE.parent / "local-apb/rtl/apb_regs.sv", HERE / "tb/top.sv"]
HARNESS = HERE.parent / "local-uvm-random/sim_main.cpp"
CATALOG = HERE.parent / "local-apb/requirements.json"
OLD_TB = HERE.parent / "local-apb/tb/apb_tb.sv"
TRACE_FIELDS = ("rst_n", "psel", "penable", "pwrite", "paddr", "pwdata", "events",
                "pready", "pslverr", "prdata", "config_before", "pending_before",
                "config_after", "pending_after")
ALL_GOALS = ({f"cross/{a}/{op}" for a in ("config", "id", "pending", "unmapped", "unaligned")
              for op in ("read", "write")} |
             {"data/zero", "data/ones", "data/alternating", "w1c/zero", "w1c/clear-all",
              "w1c/event-wins", "reset/idle", "reset/setup", "reset/access",
              "bus/back-to-back", "bus/wait"})
RESET_COVERS = {"cp_reset_seen", "cp_reset_done"}


def required_goals(wait):
    _, applicable, excluded = LEGACY.load_catalog(CATALOG, wait)
    goals = {g for r in applicable for g in r["goals"]}
    expected = ALL_GOALS - ({"bus/wait"} if wait == 0 else set())
    if goals != expected:
        raise ValueError("legacy catalog differs from the reviewed migration plan")
    return goals, excluded


def nominal_vectors(wait):
    return ([[0, 0, 0, 0, 0, 0, 0]] +
            LEGACY.transfer(wait, 0, 1, 0x13579bdf) + LEGACY.transfer(wait, 0, 0) +
            [[1, 0, 0, 0, 0, 0, 0]])


def parse_trace(output, vectors):
    lines = re.findall(r"^MIG_TRACE (.+)$", output, re.M)
    if len(lines) != len(vectors):
        raise ValueError("missing or duplicate observed cycles")
    records = []
    for cycle, (line, inputs) in enumerate(zip(lines, vectors), 1):
        words = line.split()
        if len(words) != 15 or not all(re.fullmatch(r"[0-9a-fA-F]+", w) for w in words):
            raise ValueError("invalid/unknown trace value")
        if int(words[0]) != cycle:
            raise ValueError("out-of-order observed cycle")
        record = list(map(lambda w: int(w, 16), words[1:]))
        if record[:7] != inputs:
            raise ValueError("observed inputs differ from the saved replay")
        widths = (1, 1, 1, 1, 8, 32, 4, 1, 1, 32, 32, 4, 32, 4)
        if any(n >= 1 << width for n, width in zip(record, widths)):
            raise ValueError("trace value exceeds signal width")
        records.append(record)
    return records


def legacy_trace(path, cycles):
    """Sample stable pre-edge and post-NBA values from the legacy 1 ps VCD."""
    names = ("rst_n", "psel", "penable", "pwrite", "paddr", "pwdata", "events",
             "pready", "pslverr", "prdata", "config_value", "pending")
    scope, ids, values, snapshots, times = [], {}, {}, [], []
    body = False
    stamp = None
    raw = path.read_text()
    if "$timescale 1ps $end" not in " ".join(raw.split()):
        raise ValueError("unexpected legacy VCD timescale")
    for line in raw.splitlines():
        line = line.strip()
        if not body:
            parts = line.split()
            if line.startswith("$scope"):
                scope.append(parts[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var") and scope == ["apb_tb"] and parts[4] in names:
                ids[parts[4]] = parts[3]
            elif line.startswith("$enddefinitions"):
                if ids.keys() != set(names):
                    raise ValueError("missing legacy VCD signals")
                body = True
            continue
        if line.startswith("#"):
            if stamp is not None:
                times.append(stamp)
                snapshots.append(dict(values))
            stamp = int(line[1:])
        elif line and line[0] in "01xz":
            if line[1:] in ids.values():
                values[line[1:]] = line[0]
        elif line.startswith("b"):
            bits, key = line[1:].split()
            if key in ids.values():
                values[key] = bits
    if stamp is not None:
        times.append(stamp)
        snapshots.append(dict(values))

    def at(time, field):
        index = bisect_right(times, time) - 1
        if index < 0:
            raise ValueError("missing legacy VCD observation time")
        bits = snapshots[index].get(ids[field], "x")
        if not re.fullmatch(r"[01]+", bits):
            raise ValueError("unknown legacy VCD value")
        return int(bits, 2)

    records = []
    for cycle in range(cycles):
        pre, post = 14000 + cycle * 10000, 16000 + cycle * 10000
        if not times or times[-1] < post:
            raise ValueError("legacy waveform ended before final observation")
        records.append([at(pre, name) for name in names[:10]] +
                       [at(pre, name) for name in names[10:]] +
                       [at(post, name) for name in names[10:]])
    return records


def compare_traces(old, new):
    if not old or len(old) != len(new):
        raise ValueError("empty or different trace lengths")
    mismatches = []
    for cycle, (left, right) in enumerate(zip(old, new), 1):
        if len(left) != len(TRACE_FIELDS) or len(right) != len(TRACE_FIELDS):
            raise ValueError("trace shape differs")
        for field, a, b in zip(TRACE_FIELDS, left, right):
            if a != b:
                mismatches.append(dict(cycle=cycle, field=field, legacy=a, uvm=b))
    return dict(success=not mismatches, cycles=len(old), fields=len(TRACE_FIELDS),
                differences=len(mismatches), first_differences=mismatches[:20])


def reset_counts(path, output):
    counts = {}
    for line in path.read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"C '([^']*)' (\d+)", line)
        if not match:
            raise ValueError("malformed native coverage")
        meta = dict(part.split("\x02", 1) for part in match[1].split("\x01") if part)
        if meta.get("t") != "user":
            continue
        label = meta.get("o")
        if (label not in RESET_COVERS or label in counts or
                meta.get("h") != f"TOP.top.{label}" or
                Path(meta.get("f", "")).resolve() != (HERE / "tb/top.sv").resolve()):
            raise ValueError("wrong native cover source/hierarchy/inventory")
        counts[label] = int(match[2])
    logged = Counter(re.findall(r"^MIG_SVA_COVER (\w+)$", output, re.M))
    if (counts.keys() != RESET_COVERS or set(logged) - RESET_COVERS or
            any(n <= 0 or logged[k] != n for k, n in counts.items())):
        raise ValueError("reset cover missing, unhit or inconsistent with native counters")
    return counts


def migration_goals(output):
    goals = set()
    for line in output.splitlines():
        if line.startswith("MIG_COVER"):
            match = re.fullmatch(r"MIG_COVER ([\w./-]+)", line)
            if not match:
                raise ValueError("malformed migrated goal record")
            goals.add(match[1])
    return goals


def evaluate(case, execution, output, backend):
    status, message = E.P.classify(case, execution, output)
    if status not in ("pass", "detected"):
        return False, message
    if backend == "uvm" and status == "pass":
        n = case["checks"]
        if output.count(f"MIG_COMPLETE samples={n} comparisons={n}\n") != 1:
            return False, "comparison/observation count differs"
        if output.count("MIG_OWNERSHIP passive driver=0 sequencer=0 legacy=1\n") != 1:
            return False, "passive ownership was not confirmed"
        if output.count("Accellera:1800.2:UVM:2020.3.2") != 1:
            return False, "unexpected UVM version"
        for severity in ("ERROR", "FATAL"):
            if re.findall(r"^UVM_" + severity + r"\s*:\s*(\d+)\s*$", output, re.M) != ["0"]:
                return False, "UVM errors or missing native summary"
        warnings = re.findall(r"^UVM_WARNING .*?\[([^]]+)\]", output, re.M)
        if sorted(warnings) != ["NO_DPI_USED", "NO_VISIT_CHECK"]:
            return False, "unexpected/missing UVM warning"
        if re.findall(r"^UVM_WARNING\s*:\s*(\d+)\s*$", output, re.M) != ["2"]:
            return False, "native UVM warning count differs"
    return True, message


def run(args):
    waits = (0, 1, 3) if args.wait == "all" or (args.wait is None and args.profile == "nightly") else (int(args.wait or "1"),)
    seeds = list(range(args.seed, args.seed + (3 if args.profile == "nightly" else 1)))
    transactions = args.transactions if args.transactions is not None else (2000 if args.profile == "nightly" else 200)
    plans = {}
    check_ids = ["uvm-build"]
    for wait in waits:
        normal = [("nominal", nominal_vectors(wait)), ("boundaries", LEGACY.boundary_vectors(wait))]
        normal += [(f"random-seed{s}", LEGACY.random_vectors(wait, s, transactions)) for s in seeds]
        plans[wait] = normal
        check_ids += [f"wait{wait}/legacy-build{m}" for m in range(4)]
        check_ids += [f"wait{wait}/{name}/{kind}" for name, _ in normal for kind in ("legacy", "uvm", "trace")]
        check_ids += [f"wait{wait}/mutation{m}/{kind}" for m in (1, 2, 3) for kind in ("legacy", "uvm")]
        check_ids += [f"wait{wait}/{name}" for name in ("monitor-fault", "checker-off", "active-agent", "sva-fault", "coverage")]
    sources = [Path(__file__), OLD_TB, Path(LEGACY.__file__), CATALOG, HARNESS, *SOURCES]
    e = E.Evidence("local-uvm-migration", args, sources,
                   dict(waits=list(waits), seeds=seeds, transactions=transactions,
                        vectors={str(w):[{"id": name, "rows": rows} for name, rows in cases] for w, cases in plans.items()},
                        trace_fields=TRACE_FIELDS, stage="M1-M2", rtl_mutations=[1, 2, 3]), check_ids)
    home = args.uvm_home.resolve()
    library = home / "src/uvm_pkg.sv"
    E.P.write_json(e.out / "uvm-source.json", dict(root=str(home), source_sha256={
        str(p.relative_to(home)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((home / "src").rglob("*")) if p.is_file()}))
    versions = {}
    for name in ("iverilog", "vvp", "verilator"):
        versions[name] = E.P.execute([getattr(args, name), "--version" if name == "verilator" else "-V"],
                                    e.out / f"{name}-version.log", args.timeout, e.out)
    E.P.write_json(e.out / "tools.json", versions)
    build_dir = e.out / "build"
    command = [args.verilator, "--cc", "--exe", "--build", "--timing", "--trace", "--coverage-user", "--assert",
               "-Wno-fatal", "-j", str(args.jobs), "--top-module", "top", "--Mdir", str(build_dir),
               "-I" + str(home / "src"), "+define+UVM_NO_DPI", str(library), *map(str, SOURCES), str(HARNESS)]
    built = E.P.execute(command, e.out / "build.log", args.build_timeout, e.out)
    e.check("uvm-build", not built["error"] and built["returncode"] == 0, built)
    E.P.write_json(e.out / "build.json", built)
    executions, coverage = [], {}

    def execute(wait, name, rows, backend, mutation=0, expected=None, **flags):
        directory = e.out / f"wait{wait}" / name / backend
        directory.mkdir(parents=True)
        vector_file = directory / "vectors.txt"
        vector_file.write_text("".join(f"{r} {s} {en} {w} {a:x} {d:x} {ev:x}\n" for r, s, en, w, a, d, ev in rows))
        case = dict(id=name, checks=len(rows), expected_failure=expected)
        if backend == "legacy":
            command = [args.vvp, str(e.out / f"legacy-w{wait}-m{mutation}.vvp")]
        else:
            command = [str(build_dir / "Vtop"), f"+WAIT_CYCLES={wait}", f"+MUTATION={mutation}",
                       f"+CHECKS={len(rows)}", f"+SVA_OFF={int(args.sva_off)}"]
            command += [f"+{k}={int(v)}" for k, v in flags.items()]
        command += [f"+VECTORS={vector_file}", f"+WAVE={directory}/wave.vcd"]
        result = E.P.execute(command, directory / "simulation.log", args.timeout, directory)
        output = (directory / "simulation.log").read_text(errors="replace")
        ok, detail = evaluate(case, result, output, backend)
        record = dict(backend=backend, wait=wait, case=name, expected_failure=expected,
                      success=ok, detail=detail, execution=result)
        trace, hits = None, set()
        if ok and not expected:
            try:
                if backend == "uvm":
                    trace = parse_trace(output, rows)
                    record["native_reset_covers"] = reset_counts(directory / "coverage.dat", output)
                    hits = migration_goals(output)
                else:
                    trace = legacy_trace(directory / "wave.vcd", len(rows))
                    hits = set(re.findall(r"^COVER ([\w./-]+)$", output, re.M))
                required, _ = required_goals(wait)
                if hits - required:
                    raise ValueError("unplanned legacy goal")
                E.P.write_json(directory / "normalized-trace.json", trace)
            except (OSError, ValueError, KeyError) as exc:
                ok = False
                record.update(success=False, detail=str(exc))
        record["observed_goals"] = sorted(hits)
        E.P.write_json(directory / "result.json", record)
        executions.append(record)
        return ok, record, trace, hits

    for wait in waits:
        required, excluded = required_goals(wait)
        for mutation in range(4):
            binary = e.out / f"legacy-w{wait}-m{mutation}.vvp"
            command = [args.iverilog, "-g2012", "-s", "apb_tb", f"-Papb_tb.WAIT_CYCLES={wait}",
                       f"-Papb_tb.MUTATION={mutation}", "-o", str(binary), str(SOURCES[-2]), str(OLD_TB)]
            build = E.P.execute(command, e.out / f"legacy-w{wait}-m{mutation}-build.log", args.timeout, e.out)
            e.check(f"wait{wait}/legacy-build{mutation}", not build["error"] and build["returncode"] == 0, build)
        cumulative, progress = set(), []
        for name, rows in plans[wait]:
            old_ok, old_record, old_trace, old_hits = execute(wait, name, rows, "legacy")
            new_ok, new_record, new_trace, new_hits = execute(wait, name, rows, "uvm", mutation=args.demo_bug)
            e.check(f"wait{wait}/{name}/legacy", old_ok, old_record)
            e.check(f"wait{wait}/{name}/uvm", new_ok, new_record)
            comparison = dict(success=False, reason="one environment did not complete valid checks")
            if old_ok and new_ok:
                comparison = compare_traces(old_trace, new_trace)
                comparison["same_goal_set"] = old_hits == new_hits
                comparison["success"] &= old_hits == new_hits
            E.P.write_json(e.out / f"wait{wait}" / name / "comparison.json", comparison)
            e.check(f"wait{wait}/{name}/trace", comparison["success"], comparison)
            if old_ok and new_ok and comparison["success"]:
                cumulative.update(new_hits)
            progress.append(dict(case=name, cumulative_hit=len(required & cumulative), required=len(required),
                                 missing=sorted(required - cumulative), valid=comparison["success"]))
        for mutation, old_label, new_label in ((1, "APB_STATE", "UVM_CONFIG"),
                                                (2, "APB_W1C", "UVM_PENDING"),
                                                (3, "APB_ERROR_SIDE_EFFECT", "UVM_CONFIG")):
            for backend, label in (("legacy", old_label), ("uvm", new_label)):
                ok, record, _, _ = execute(wait, f"mutation{mutation}", LEGACY.boundary_vectors(wait),
                                           backend, mutation=mutation, expected=label)
                e.check(f"wait{wait}/mutation{mutation}/{backend}", ok, record)
        diagnostics = [("monitor-fault", "UVM_CONFIG", dict(MONITOR_FAULT=1)),
                       ("checker-off", "MIG_COMPARISONS", dict(CHECKER_OFF=1)),
                       ("active-agent", "MIG_OWNERSHIP", dict(ACTIVE=1)),
                       ("sva-fault", "MIG_SYNC_RESET", dict(SVA_FAULT=1))]
        for name, label, flags in diagnostics:
            ok, record, _, _ = execute(wait, name, nominal_vectors(wait), "uvm", expected=label, **flags)
            e.check(f"wait{wait}/{name}", ok, record)
        closed = (cumulative == required and progress[0]["cumulative_hit"] < len(required) and
                  progress[1]["cumulative_hit"] == len(required))
        coverage[str(wait)] = dict(success=closed, required=len(required), hit=len(required & cumulative),
                                   missing=sorted(required - cumulative), excluded=excluded, progress=progress)
        e.check(f"wait{wait}/coverage", closed, coverage[str(wait)])
    E.P.write_json(e.out / "coverage-progress.json", coverage)
    E.P.write_json(e.out / "executions.json", executions)
    return e.finish()


def main():
    parser = E.parser(__doc__, "local-uvm-migration")
    parser.add_argument("--uvm-home", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--wait", choices=("all", "0", "1", "3"))
    parser.add_argument("--transactions", type=int)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--build-timeout", type=float, default=300)
    parser.add_argument("--demo-bug", type=int, choices=range(4), default=0)
    parser.add_argument("--sva-off", action="store_true", help="negative demo: disable native reset assertions and covers")
    args = parser.parse_args()
    E.validate(parser, args)
    if (not (args.uvm_home / "src/uvm_pkg.sv").is_file() or args.jobs <= 0 or
            not math.isfinite(args.build_timeout) or args.build_timeout <= 0 or
            (args.transactions is not None and not 1 <= args.transactions <= 10000)):
        parser.error("requires a prepared UVM library, positive time/jobs and 1..10000 transactions")
    try:
        return run(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("RUNNER_ERROR", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
