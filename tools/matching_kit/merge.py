#!/usr/bin/env python3
"""Apply the accepted proposals of a work directory to the coverage ledgers.

Usage:
    merge.py PROPOSALS_DIR --reviewer TEXT --date YYYY-MM-DD [--dry-run]

Every *.jsonl file of PROPOSALS_DIR (not *.verdicts.jsonl) is read. A proposal
is applied only when the latest verdict of its key is "accept", and only after
it passes the checks of propose.py again against the ledgers as they are
before this merge. Acceptance snapshots must match the current proposal, test
inputs and requirements. Checks go to coverage/behaviors.json, with the reviewed
input digest; groups become check_groups; holds are added to
coverage/test-matching-reviews.json. Proposals already applied are skipped, so
running it again changes nothing. A requirement that gets a group has every
one of its checks in some group, as validate() requires.

Then regenerate the reports (docs/requirements-to-tests-method.md, section 9).

Local revision (2026-10-26): reject stale or unversioned approvals before writing.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import propose
from propose import ROOT, Rejected, State, read_jsonl

sys.path.insert(0, str(ROOT / "tools"))
import behavior_coverage  # noqa: E402

SCOPE = ("Listed requirement decisions only; this is not completion of every observation "
         "or requirement in the test.")


def accepted_proposals(directory: Path) -> list[tuple[str, dict, dict]]:
    out = []
    for path in sorted(directory.glob("*.jsonl")):
        if path.name.endswith(".verdicts.jsonl"):
            continue
        verdicts = {v["key"]: v for v in read_jsonl(path.with_name(path.name + ".verdicts.jsonl"))}
        for p in read_jsonl(path):
            v = verdicts.get(p["key"])
            if v and v["verdict"] == "accept":
                out.append((path.name, p, v))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("proposals", type=Path)
    ap.add_argument("--reviewer", required=True,
                    help='who reviewed, e.g. "<model> (AI); not an independent human review"')
    ap.add_argument("--date", required=True, help="review date, YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        ap.error("--date must be YYYY-MM-DD")

    state = State()   # the ledgers before this merge, for every check
    data = json.loads((ROOT / "coverage/behaviors.json").read_text())
    rows = {r["id"]: r for r in data["requirements"]}
    reviews_doc = json.loads((ROOT / "coverage/test-matching-reviews.json").read_text())
    reviews = {rv["test"]: rv for rv in reviews_doc["reviews"]}
    accepted = accepted_proposals(args.proposals)
    valid, skipped = [], []
    for source, p, v in accepted:
        kind = p["type"]
        if kind == "check" and any(c["test"] == p["test"] for c in rows[p["requirement_id"]]["checks"]):
            continue
        if kind == "group" and any(g["id"] == p["group_id"]
                                   for g in rows[p["requirement_id"]].get("check_groups", [])):
            continue
        if kind == "hold":
            rv = reviews.get(p["test"])
            # A recorded decision may have gained a finding number ("M98: ...").
            if rv and any(d["requirement_ids"] == p["requirement_ids"]
                          and re.sub(r"^M\d+:\s*", "", d["explanation"]) == p["explanation"]
                          for d in rv["decisions"]):
                continue
        try:
            propose.RECORDS[kind](state, p)
            propose.verify_approval(state, p, v)
        except (Rejected, OSError, ValueError) as e:
            skipped.append((p["key"], str(e)))
            continue
        valid.append((source, p, v))

    if skipped:
        print(f"accepted={len(accepted)} applied=0 skipped={len(skipped)}")
        for key, why in skipped:
            print(f"SKIP {key}: {why}")
        return 1

    log, grouped = [], {}
    for source, p, v in valid:
        kind = p["type"]
        digests = v["review_snapshot"]["test_inputs_sha256"]
        if kind == "check":
            r = rows[p["requirement_id"]]
            if any(c["test"] == p["test"] for c in r["checks"]):
                continue
            r["checks"].append({"test": p["test"],
                                "observation": f"{p['observation']} 区別: {p['rationale']}",
                                "reviewed_on": args.date, "reviewer": args.reviewer,
                                "inputs_sha256": digests[p["test"]], "evidence": p["evidence"]})
        elif kind == "group":
            r = rows[p["requirement_id"]]
            for m in p["members"]:
                if not any(c["test"] == m["test"] for c in r["checks"]):
                    r["checks"].append({"test": m["test"], "observation": m["observation"],
                                        "reviewed_on": args.date, "reviewer": args.reviewer,
                                        "inputs_sha256": digests[m["test"]],
                                        "evidence": m["evidence"]})
            r.setdefault("check_groups", []).append(
                {"id": p["group_id"], "tests": [m["test"] for m in p["members"]],
                 "reviewed_on": args.date, "reviewer": args.reviewer,
                 "observation": f"{p['collective_observation']} 区別: {p['rationale']}"})
            grouped[r["id"]] = r
        else:
            rv = reviews.get(p["test"])
            if rv is None:
                rv = {"test": p["test"], "inputs_sha256": digests[p["test"]],
                      "reviewed_on": args.date, "reviewer": args.reviewer, "scope": SCOPE,
                      "decisions": []}
                reviews[p["test"]] = rv
                reviews_doc["reviews"].append(rv)
            rv["decisions"].append({"requirement_ids": p["requirement_ids"],
                                    "disposition": p["disposition"],
                                    "explanation": p["explanation"],
                                    "reviewed_on": args.date, "reviewer": args.reviewer,
                                    "evidence": p["evidence"]})
        log.append({"key": p["key"], "source": source, "verdict": v["reason"],
                    "verifier": v.get("verifier"), "review_snapshot": v["review_snapshot"]})

    for r in grouped.values():
        in_groups = {t for g in r["check_groups"] for t in g["tests"]}
        for c in r["checks"]:
            if c["test"] not in in_groups:
                r["check_groups"].append(
                    {"id": "standalone-" + Path(c["test"]).stem.replace("_", "-"),
                     "tests": [c["test"]], "reviewed_on": args.date, "reviewer": args.reviewer,
                     "observation": "This reviewed check alone satisfies the requirement."})

    behavior_coverage.validate(json.loads((ROOT / "coverage/standard-sections.json").read_text()),
                               data)
    mapped = sum(bool(r["checks"]) for r in data["requirements"])
    print(f"accepted={len(accepted)} applied={len(log)} skipped={len(skipped)} mapped_now={mapped}")
    for key, why in skipped:
        print(f"SKIP {key}: {why[:200]}")
    if args.dry_run:
        return 0
    (ROOT / "coverage/behaviors.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "coverage/test-matching-reviews.json").write_text(
        json.dumps(reviews_doc, ensure_ascii=False, indent=2) + "\n")
    log_file = args.proposals / "merged-log.json"
    prior = json.loads(log_file.read_text()) if log_file.exists() else []
    log_file.write_text(json.dumps(prior + log, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
