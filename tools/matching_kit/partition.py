#!/usr/bin/env python3
"""Split the open requirements into assignment files for parallel review.

Usage:
    partition.py OUT_DIR [--target N] [--uncovered-target N] [--skip-roots "B F 34"]

An open requirement has no checks and no interpretation issue. Those that some
test cites (a candidate test, not already ruled out by a scoped hold) are cut,
in section order and never inside a section, into files of about N
requirements, labelled p01, p02, ...: they are for matching first. The others
have no candidate test and need new tests; they are cut the same way into
g.. (clauses 1-41), a.. (Annex A) and h.. (the other annexes) files of about
the uncovered target. Roots in --skip-roots are left out. Each file is
{"label", "requirement_ids", "clauses"}, the input of propose.py scope.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from behavior_coverage import section_key  # noqa: E402


def chunks(ids: list[str], clause_of: dict, target: int) -> list[list[str]]:
    by_clause = defaultdict(list)
    for rid in ids:
        by_clause[clause_of[rid]].append(rid)
    out, current = [], []
    for clause in sorted(by_clause, key=section_key):
        if current and len(current) + len(by_clause[clause]) > target * 1.25 \
                and len(current) >= target * 0.6:
            out.append(current)
            current = []
        current += sorted(by_clause[clause])
        if len(current) >= target:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def write(out_dir: Path, prefix: str, groups: list[list[str]], clause_of: dict) -> None:
    for n, ids in enumerate(groups, 1):
        clauses = sorted({clause_of[i] for i in ids}, key=section_key)
        label = f"{prefix}{n:02d}-{clauses[0]}_to_{clauses[-1]}"
        (out_dir / f"{label}.json").write_text(json.dumps(
            {"label": label, "requirement_ids": ids, "clauses": clauses}, indent=1) + "\n")
        print(f"{label}\t{len(ids)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--target", type=int, default=220)
    ap.add_argument("--uncovered-target", type=int, default=140)
    ap.add_argument("--skip-roots", default="")
    args = ap.parse_args()
    rows = json.loads((ROOT / "coverage/behaviors.json").read_text())["requirements"]
    tests = json.loads((ROOT / "coverage/test-matching.json").read_text())["tests"]
    reviews = json.loads((ROOT / "coverage/test-matching-reviews.json").read_text())["reviews"]
    held = {(rv["test"], rid) for rv in reviews for d in rv["decisions"] for rid in d["requirement_ids"]}
    skip = set(args.skip_roots.split())
    clause_of = {r["id"]: r["clause"] for r in rows}
    open_ids = [r["id"] for r in rows if not r["checks"] and not r.get("interpretation_issue")
                and r["clause"].split(".")[0] not in skip]
    open_set = set(open_ids)
    covered = {rid for t in tests for rid in t["unapproved_candidate_ids"]
               if rid in open_set and (t["test"], rid) not in held}
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write(args.out_dir, "p", chunks(sorted(covered), clause_of, args.target), clause_of)
    rest = [i for i in open_ids if i not in covered]
    root = lambda i: clause_of[i].split(".")[0]
    write(args.out_dir, "g", chunks([i for i in rest if root(i).isdigit()], clause_of,
                                    args.uncovered_target), clause_of)
    write(args.out_dir, "a", chunks([i for i in rest if root(i) == "A"], clause_of,
                                    args.uncovered_target), clause_of)
    write(args.out_dir, "h", chunks([i for i in rest if not root(i).isdigit() and root(i) != "A"],
                                    clause_of, args.uncovered_target), clause_of)
    return 0


if __name__ == "__main__":
    sys.exit(main())
