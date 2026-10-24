#!/usr/bin/env python3
"""Writes the generated tests to tests/gen/, or checks that they are up to date.

Usage:
    python3 generators/generate.py            write tests/gen/ (and remove stale files)
    python3 generators/generate.py --check    exit with 1 if tests/gen/ is out of date
    python3 generators/generate.py --list     print the name of every generated test

See common.py for the form of a generator, and "Generated tests" in README.md.
"""

import argparse
import sys

import common
import keywords
import scheduling
import strength
import wide_paths
import width_sign
import xz_propagation

GENERATORS = [scheduling, width_sign, xz_propagation, strength, wide_paths, keywords]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="only check that tests/gen/ is up to date")
    ap.add_argument("--list", action="store_true", help="print the names of the generated tests")
    args = ap.parse_args()

    files = common.outputs(GENERATORS)
    if args.list:
        for path in sorted(files):
            if path.suffix == ".sv":
                print(path.stem)
        return 0
    present = {p for p in common.GEN.rglob("*") if p.is_file()} if common.GEN.exists() else set()
    stale = sorted(present - set(files))
    changed = sorted(p for p, text in files.items()
                     if not p.exists() or p.read_text(encoding="utf-8") != text)
    if args.check:
        for p in changed + stale:
            print(f"out of date: {p.relative_to(common.ROOT)}")
        if changed or stale:
            print("run python3 generators/generate.py")
        return 1 if changed or stale else 0
    for p in stale:
        p.unlink()
    for p in changed:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(files[p], encoding="utf-8")
    print(f"{sum(p.suffix == '.sv' for p in files)} generated tests; "
          f"{len(changed)} files written, {len(stale)} removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
