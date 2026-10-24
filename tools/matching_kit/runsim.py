#!/usr/bin/env python3
"""Run tests with Icarus Verilog 13.0 and Verilator 5.052 (seeds 1 and 73) and
say, for each test and run, whether it produces its expected result.

Usage:
    runsim.py [--iverilog-bin DIR] [--verilator PATH] tests/chNN/test_x.sv [...]

DIR is the bin directory of Icarus Verilog 13.0 (default: $ICARUS13_BIN, else
the iverilog on PATH). The runs use tools/run_icarus.py and
tools/run_verilator.py --all and write their JSON to a temporary directory, so
nothing in the repository changes. A test matches a release when that run
passes; use it to decide :oracle: (README, "Where the expected outputs come
from"). With ccache on PATH, Verilator models compile through it.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = (("icarus13", "i.json"), ("verilator-seed1", "v1.json"), ("verilator-seed73", "v73.json"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--iverilog-bin", default=os.environ.get("ICARUS13_BIN"))
    ap.add_argument("--verilator", default="verilator")
    ap.add_argument("tests", nargs="+")
    args = ap.parse_args()
    env = dict(os.environ)
    if shutil.which("ccache"):
        env["OBJCACHE"] = "ccache"
    icarus = [*(["--iverilog-bin", args.iverilog_bin] if args.iverilog_bin else [])]
    with tempfile.TemporaryDirectory() as d:
        commands = [
            [sys.executable, "tools/run_icarus.py", *icarus, "--json", f"{d}/i.json", *args.tests],
            [sys.executable, "tools/run_verilator.py", "--verilator", args.verilator, "--all",
             "--seed", "1", "--json", f"{d}/v1.json", *args.tests],
            [sys.executable, "tools/run_verilator.py", "--verilator", args.verilator, "--all",
             "--seed", "73", "--json", f"{d}/v73.json", *args.tests],
        ]
        procs = [subprocess.Popen(c, cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL) for c in commands]
        for p in procs:
            p.wait()
        results = {name: json.loads(Path(d, file).read_text()) for name, file in RUNS}
    for t in args.tests:
        tid = (ROOT / t).resolve().relative_to(ROOT / "tests").with_suffix("").as_posix()
        print(f"== {t}")
        for name, data in results.items():
            r = data["tests"].get(tid, {})
            print(f"  {name:17s} {'MATCHES' if r.get('status') == 'pass' else 'differs'}  "
                  f"{r.get('reason', '')[:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
