#!/usr/bin/env python3
"""Run the registered pure-Icarus examples through an explicit kirimasim adapter.

The adapter preserves the original runners and their verdicts. Its .vvp files
are JSON recipes, not executable Icarus images; SIR is only lowering evidence.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
PARAM_TOP = "kirimasim_parameters"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def parse_compile(argv):
    """Accept only the exact Icarus CLI subset used by these example runners."""
    top = output = None
    parameters = {}
    sources = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-g2012":
            pass
        elif arg in ("-s", "-o"):
            i += 1
            if i == len(argv):
                raise ValueError("missing argument for " + arg)
            if arg == "-s":
                if top is not None:
                    raise ValueError("multiple top selections")
                top = argv[i]
            else:
                if output is not None:
                    raise ValueError("multiple output selections")
                output = Path(argv[i]).absolute()
        elif arg.startswith("-P"):
            match = re.fullmatch(r"-P([A-Za-z_]\w*)\.([A-Za-z_]\w*)=(-?\d+)", arg)
            if not match:
                raise ValueError("only decimal top-level parameter overrides are supported: " + arg)
            key = match.group(1, 2)
            if key in parameters:
                raise ValueError("duplicate parameter override")
            parameters[key] = match[3]
        elif arg.startswith(("-", "+")):
            raise ValueError("unsupported compiler option: " + arg)
        else:
            path = Path(arg).absolute()
            if path.suffix not in (".sv", ".v") or not path.is_file():
                raise ValueError("missing/non-Verilog source: " + arg)
            sources.append(path)
        i += 1
    if not top or not re.fullmatch(r"[A-Za-z_]\w*", top) or top == PARAM_TOP or output is None or not sources:
        raise ValueError("one top, output and Verilog sources are required")
    if any(name != top for name, _ in parameters):
        raise ValueError("only parameters of the selected top can be overridden")
    return top, output, parameters, sources


def parameter_source(parameters):
    # A second, inert root preserves the original testbench hierarchy, including
    # $dumpvars(0, original_top). Repeated --top selects exactly these two roots.
    return "`timescale 1ns/1ps\nmodule " + PARAM_TOP + ";\n" + "".join(
        f"  defparam {top}.{name} = {value};\n"
        for (top, name), value in parameters.items()) + "endmodule\n"


def native(command, phase, recipe, config):
    event = dict(phase=phase, recipe=str(recipe), cwd=str(Path.cwd()), command=command,
                 adapter_sha256=digest(__file__), returncode=None, error=None)
    try:
        result = subprocess.run(command, capture_output=True, timeout=config["timeout"])
        event["returncode"] = result.returncode
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        event.update(returncode=124, error="host timeout")
        stdout, stderr = exc.stdout or b"", (exc.stderr or b"") + b"\nKIRIMASIM_ADAPTER host timeout\n"
    except OSError as exc:
        event.update(returncode=127, error=str(exc))
        stdout, stderr = b"", str(exc).encode()
    diagnostic = stderr.decode(errors="replace")
    event["unsupported"] = re.findall(r"error: unsupported: ([^\n]+)", diagnostic)
    event["diagnostic"] = diagnostic[-6000:]
    write(Path(config["events"]) / (uuid.uuid4().hex + ".json"), event)
    if phase == "lower":
        recipe.with_suffix(".sir").write_bytes(stdout)
        print("KIRIMASIM_ADAPTER: lowering only; SIR is not a saved simulation image", flush=True)
    else:
        sys.stdout.buffer.write(stdout)
        sys.stdout.buffer.flush()
    sys.stderr.buffer.write(stderr)
    sys.stderr.buffer.flush()
    code = event["returncode"]
    return code if code >= 0 else 128 - code


def verify_recipe(recipe, config):
    data = json.loads(Path(recipe).read_text())
    if data.get("format") != "kirimasim-source-recipe-v1":
        raise ValueError("not a kirimasim source recipe")
    if data["binary_sha256"] != config["binary_sha256"] or digest(config["binary"]) != config["binary_sha256"]:
        raise ValueError("kirimasim binary changed")
    for name, expected in data["source_sha256"].items():
        if digest(name) != expected:
            raise ValueError("source changed after lowering: " + name)
    return data


def adapter(mode, argv):
    config = json.loads(Path(os.environ["KIRIMASIM_ADAPTER_CONFIG"]).read_text())
    if argv == ["-V"]:
        print("kirimasim adapter (" + mode + " interface; not Icarus Verilog)")
        print(config["version"])
        return 0
    if digest(config["binary"]) != config["binary_sha256"]:
        raise ValueError("kirimasim binary changed")
    if mode == "compile":
        top, output, parameters, sources = parse_compile(argv)
        if output.exists():
            output.unlink()
        overrides = output.with_suffix(".parameters.sv")
        overrides.write_text(parameter_source(parameters))
        command = [config["binary"], "--top=" + top, "--top=" + PARAM_TOP,
                   "--timescale=1ns/1ps",
                   "--seed=0", "--stop=error", "--max-wall-time=" + str(config["timeout"]),
                   *map(str, sources), str(overrides)]
        data = dict(format="kirimasim-source-recipe-v1", command=command,
                    binary_sha256=config["binary_sha256"],
                    source_sha256={str(p): digest(p) for p in [*sources, overrides]})
        code = native([*command, "--dump-sir"], "lower", output, config)
        if code == 0:
            if not output.with_suffix(".sir").stat().st_size:
                raise ValueError("empty lowered SIR")
            write(output, data)
        return code
    if not argv or any(not arg.startswith("+") for arg in argv[1:]):
        raise ValueError("run requires a source recipe followed by plusargs")
    recipe = Path(argv[0]).absolute()
    data = verify_recipe(recipe, config)
    return native([*data["command"], *argv[1:]], "run", recipe, config)


def selected_entries(registry, names):
    eligible = {e["id"]: e for e in registry["examples"]
                if e["kind"] == "simulation" and set(e["tools"]) == {"iverilog", "vvp"}}
    if names and set(names) - eligible.keys():
        raise ValueError("only registered pure-Icarus simulation examples can be selected")
    return sorted(set(names or eligible))


def audit_events(events):
    lower = [e for e in events if e["phase"] == "lower"]
    runs = [e for e in events if e["phase"] == "run"]
    bad = [e for e in events if e.get("error") or e.get("unsupported") or
           e["returncode"] not in ((0,) if e["phase"] == "lower" else (0, 1))]
    return dict(success=bool(lower and runs) and not bad, lowering=len(lower),
                simulations=len(runs), abnormal=len(bad))


def snapshot_inputs():
    return sorted({Path(__file__), *[p for base in ("examples", "tools")
                   for p in (ROOT / base).rglob("*")
                   if p.is_file() and not any(x in p.parts for x in
                   ("node_modules", "__pycache__")) and p.suffix in
                   (".py", ".sv", ".v", ".json", ".hex", ".txt")]})


def run(a):
    registry = json.loads((ROOT / "tools/regressions.json").read_text())
    selected = selected_entries(registry, a.example)
    a.out.mkdir(parents=True, exist_ok=False)
    binary = a.out / "bin/kirimasim"
    binary.parent.mkdir()
    shutil.copy2(a.kirimasim, binary)
    events = a.out / "events"
    events.mkdir()
    version = subprocess.check_output([binary, "--version"], text=True, timeout=30).strip()
    inputs = snapshot_inputs()
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    config = dict(binary=str(binary), binary_sha256=digest(binary), version=version,
                  events=str(events), timeout=a.command_timeout)
    write(a.out / "adapter.json", config)
    env = dict(os.environ, KIRIMASIM_ADAPTER_CONFIG=str(a.out / "adapter.json"))
    for name, mode in (("iverilog", "compile"), ("vvp", "run")):
        shim = binary.parent / name
        shim.write_text("#!" + sys.executable + "\nimport os, sys\nos.execv(" +
                        repr(sys.executable) + ", [" + repr(sys.executable) + ", " +
                        repr(str(Path(__file__).resolve())) + ", '--adapter-" + mode + "', *sys.argv[1:]])\n")
        shim.chmod(0o755)
    command = [sys.executable, str(ROOT / "tools/run_regression.py"),
               "--suite", "simulation", "--profile", a.profile, "--seed", str(a.seed),
               "--jobs", str(a.jobs), "--job-timeout", str(a.job_timeout),
               "--command-timeout", str(a.command_timeout), "--child-timeout", str(a.job_timeout),
               "--tool-bin", str(binary.parent), "--out", str(a.out / "campaign")]
    for name in selected:
        command += ["--example", name]
    write(a.out / "manifest.json", dict(created_at=datetime.now(timezone.utc).isoformat(),
          command=command, selected=selected, source_sha256=hashes, tool=config))
    result = subprocess.run(command, env=env)
    summary = json.loads((a.out / "campaign/summary.json").read_text())
    recorded = [json.loads(p.read_text()) for p in sorted(events.glob("*.json"))]
    rows = []
    for row in summary["results"]:
        job = (a.out / "campaign/runs" / row["id"]).resolve()
        own = [e for e in recorded if Path(e["cwd"]).is_relative_to(job)]
        audit = audit_events(own)
        rows.append(dict(id=row["id"], example=row.get("example"),
                         success=row["success"] and audit["success"],
                         runner_success=row["success"], native=audit, message=row["message"]))
    changed = [name for name, value in hashes.items() if not (ROOT / name).is_file() or digest(ROOT / name) != value]
    if snapshot_inputs() != inputs:
        changed.append("source inventory")
    if digest(binary) != config["binary_sha256"]:
        changed.append("kirimasim binary")
    complete = summary.get("complete") is True and len(rows) == summary["planned"]
    success = complete and not changed and result.returncode == 0 and all(r["success"] for r in rows)
    report = dict(success=success, complete=complete, profile=a.profile, seed=a.seed,
                  selected_examples=len(selected), planned=summary["planned"],
                  passed=sum(r["success"] for r in rows), source_changes=changed,
                  native=audit_events(recorded), results=rows,
                  returncodes=dict(Counter(str(e["returncode"]) for e in recorded)))
    write(a.out / "summary.json", report)
    print("Kirimasim:", report["passed"], "/", report["planned"], "jobs passed; artifacts:", a.out)
    return 0 if success else 1


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] in ("--adapter-compile", "--adapter-run"):
            return adapter(sys.argv[1].removeprefix("--adapter-"), sys.argv[2:])
        p = argparse.ArgumentParser(description=__doc__)
        p.add_argument("--kirimasim", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--example", action="append")
        p.add_argument("--profile", choices=("smoke", "nightly"), default="smoke")
        p.add_argument("--seed", type=int, default=17)
        p.add_argument("--jobs", type=int, default=2)
        p.add_argument("--command-timeout", type=float, default=60)
        p.add_argument("--job-timeout", type=float, default=900)
        a = p.parse_args()
        a.out = a.out.resolve()
        a.kirimasim = a.kirimasim.resolve()
        if a.out.exists() or not a.kirimasim.is_file() or not 1 <= a.jobs <= 16 or not 0 <= a.seed <= 2**31 - 4 or any(
                not math.isfinite(x) or x <= 0 for x in (a.command_timeout, a.job_timeout)):
            p.error("existing kirimasim, fresh --out, jobs 1..16, valid seed and finite positive timeouts required")
        return run(a)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print("KIRIMASIM_ADAPTER_ERROR:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
