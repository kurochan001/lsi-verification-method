#!/usr/bin/env python3
"""Propose, check and judge links between IEEE 1800-2023 requirements and tests.

The repository is only read. Proposals and verdicts go to JSONL files in a
work directory outside it, one JSON object per line, and merge.py applies the
accepted ones. Each proposal is checked when it is added, with the conditions
of tools/behavior_coverage.py validate() and the exclusions below, so that a
proposal that could never be merged is refused at once.

    propose.py scope ASSIGNMENT.json [--out FILE ...]   assigned requirements and their state
    propose.py req ID [ID ...]                          requirement, source, candidates, holds
    propose.py test tests/chN/test_x.sv                 header, input files, links, holds
    propose.py add   --out FILE < JSON                  propose a check
    propose.py group --out FILE < JSON                  propose an AND group of checks
    propose.py hold  --out FILE < JSON                  record a scoped hold decision
    propose.py show  --out FILE                         proposals and their verdicts
    propose.py verdict --out FILE --key KEY (--accept | --reject) --reason TEXT [--verifier NAME]
    propose.py testverdict --out FILE --test tests/... (--ok | --defective) --reason TEXT [--verifier NAME]

The verdicts of FILE go to FILE.verdicts.jsonl; the latest verdict of a key
counts. See docs/requirements-to-tests-method.md for the review criteria.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import suite_results  # noqa: E402

KIT = Path(__file__).resolve().parent
DISPOSITIONS = {"partial_observation", "oracle_issue", "citation_refinement",
                "compound_requirement"}
# No new links from these files (findings M04 and M84 of
# docs/existing-test-matching-review-20261022.md).
BLOCKED_TESTS = {
    "tests/ch26/test_std_package_access.sv":
        "M04: try_get success fixed at 1 (oracle issue); no new mappings",
    "tests/ch7/test_tagged_union_packed.sv":
        "M84: 3-member tag encoding basis unresolved; no new mappings",
}
# Links withdrawn by the final audit of the 20% matching; not to be re-registered.
WITHDRAWN = KIT / "withdrawn-20261023.json"


class Rejected(Exception):
    """A proposal that cannot be accepted, with the reason."""


def reject(msg: str):
    raise Rejected(msg)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class State:
    """The ledger, the review ledger and the test inventory, read once."""

    def __init__(self):
        data = json.loads((ROOT / "coverage/behaviors.json").read_text())
        self.rows = {r["id"]: r for r in data["requirements"]}
        reviews = json.loads((ROOT / "coverage/test-matching-reviews.json").read_text())["reviews"]
        self.holds = defaultdict(list)
        for review in reviews:
            for decision in review["decisions"]:
                for rid in decision["requirement_ids"]:
                    self.holds[(review["test"], rid)].append(decision)
        self.withdrawn = {(check["test"], rid)
                          for rid, check in json.loads(WITHDRAWN.read_text())}
        inventory = json.loads((ROOT / "coverage/test-matching.json").read_text())["tests"]
        self.tests = {t["test"]: t for t in inventory}
        self._add_new_tests()

    def _add_new_tests(self):
        """Tests written after coverage/test-matching.json was last generated."""
        by_clause = defaultdict(list)
        for r in self.rows.values():
            by_clause[r["clause"]].append(r)
        for path in suite_results.find_tests():
            name = path.relative_to(ROOT).as_posix()
            if name in self.tests:
                continue
            fields = suite_results.header(path)
            clauses = list(dict.fromkeys(fields.get("lrm", "").split()[1:]))
            negative = bool(fields.get("should_fail_because"))
            linked = sorted(r["id"] for r in self.rows.values()
                            if any(c["test"] == name for c in r["checks"]))
            candidates = sorted(r["id"] for c in clauses for r in by_clause[c]
                                if r["id"] not in linked and not r.get("interpretation_issue")
                                and (r["kind"] == "error") == negative)
            self.tests[name] = {"test": name, "cited_clauses": clauses, "negative_test": negative,
                                "registered_requirement_ids": linked,
                                "unapproved_candidate_ids": candidates}

    def candidates(self, row: dict) -> list[str]:
        return sorted(name for name, t in self.tests.items()
                      if row["clause"] in t["cited_clauses"]
                      and (row["kind"] == "error") == t["negative_test"])


def check_member(state: State, rid: str, m: dict, standalone: bool) -> None:
    """The conditions of behavior_coverage.validate() for one check, and the
    exclusions: interpretation issues, existing holds, withdrawn links."""
    r = state.rows.get(rid) or reject(f"unknown requirement {rid}")
    if r.get("interpretation_issue"):
        reject(f"{rid} has an interpretation issue; mapping is forbidden")
    if r["checks"]:
        reject(f"{rid} is already mapped; only unmapped requirements are in scope")
    name = m.get("test", "")
    if name not in state.tests:
        reject(f"not a suite test: {name}")
    if name in BLOCKED_TESTS:
        reject(f"{name}: {BLOCKED_TESTS[name]}")
    if (name, rid) in state.holds:
        reject(f"existing scoped hold for {rid} on {name}: "
               + " / ".join(d["explanation"] for d in state.holds[(name, rid)]))
    if (name, rid) in state.withdrawn:
        reject(f"{rid} on {name} was withdrawn by an earlier audit; do not re-register")
    test = ROOT / name
    fields = suite_results.header(test)
    if r["clause"] not in fields.get("lrm", "").split()[1:]:
        reject(f"{name} does not cite clause {r['clause']} in :lrm:")
    if bool(fields.get("should_fail_because")) != (r["kind"] == "error"):
        reject(f"negative/positive mismatch: requirement kind={r['kind']}, test negative="
               f"{bool(fields.get('should_fail_because'))}")
    if len((m.get("observation") or "").strip()) < 25:
        reject("observation must describe the stimulus and the checked values (>= 25 chars)")
    if standalone and len((m.get("rationale") or "").strip()) < 25:
        reject("rationale must say how a wrong implementation changes the output (>= 25 chars)")
    anchors = m.get("evidence") or []
    if not any(a.get("file") == name for a in anchors):
        reject("evidence must include a stimulus anchor in the test .sv itself")
    inputs = {p.relative_to(ROOT).as_posix() for p in suite_results.input_files(test)}
    expected = fields.get("expected_stdout", "")
    expected_name = ((test.parent / expected[1:]).resolve().relative_to(ROOT).as_posix()
                     if expected.startswith("@") else name)
    if r["kind"] != "error":
        if not any(a.get("file") == expected_name for a in anchors):
            reject(f"evidence must include an anchor in the checked output {expected_name}")
    elif not any("expected_stderr_regex" in a.get("contains", "") for a in anchors):
        reject("an error-kind link needs an anchor with the :expected_stderr_regex: line")
    for a in anchors:
        f = a.get("file", "")
        if f not in inputs:
            reject(f"evidence file is not a test input: {f}")
        text = a.get("contains") or ""
        if len(text.strip()) < 4:
            reject(f"anchor too short to be meaningful in {f}: {text!r}")
        if text not in (ROOT / f).read_text(encoding="utf-8"):
            reject(f"anchor text not found verbatim in {f}: {text!r}")


def check_record(state: State, p: dict) -> dict:
    """Validate a check proposal and return its record."""
    rid = p.get("requirement_id", "")
    check_member(state, rid, p, standalone=True)
    return {"key": f"check|{rid}|{p['test']}", "type": "check", "requirement_id": rid,
            "test": p["test"], "observation": p["observation"].strip(),
            "rationale": p["rationale"].strip(), "evidence": p["evidence"]}


def group_record(state: State, p: dict) -> dict:
    """Validate an AND group proposal and return its record."""
    rid = p.get("requirement_id", "")
    members = p.get("members") or []
    if len(members) < 2 or len({m.get("test") for m in members}) != len(members):
        reject("a group needs at least two distinct member tests")
    for m in members:
        check_member(state, rid, m, standalone=False)
    gid = p.get("group_id", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", gid):
        reject("group_id must match [A-Za-z0-9_.-]+")
    if (len((p.get("collective_observation") or "").strip()) < 25
            or len((p.get("rationale") or "").strip()) < 25):
        reject("collective_observation and rationale are required (>= 25 chars each)")
    return {"key": f"group|{rid}|{gid}", "type": "group", "requirement_id": rid, "group_id": gid,
            "collective_observation": p["collective_observation"].strip(),
            "rationale": p["rationale"].strip(),
            "members": [{"test": m["test"], "observation": m["observation"].strip(),
                         "evidence": m["evidence"]} for m in members]}


def hold_record(state: State, p: dict) -> dict:
    """Validate a scoped hold decision and return its record."""
    name = p.get("test", "")
    if name not in state.tests:
        reject(f"not a suite test: {name}")
    ids = p.get("requirement_ids") or []
    if not ids or len(ids) != len(set(ids)) or any(i not in state.rows for i in ids):
        reject("requirement_ids must be distinct known IDs")
    if p.get("disposition") not in DISPOSITIONS:
        reject(f"disposition must be one of {sorted(DISPOSITIONS)}")
    if len((p.get("explanation") or "").strip()) < 30:
        reject("explanation must state the missing observation or the oracle problem")
    anchors = p.get("evidence") or []
    if not any(a.get("file") == name for a in anchors):
        reject("evidence must include an anchor in the test .sv")
    inputs = {q.relative_to(ROOT).as_posix() for q in suite_results.input_files(ROOT / name)}
    for a in anchors:
        if (a.get("file") not in inputs or not a.get("contains")
                or a["contains"] not in (ROOT / a["file"]).read_text(encoding="utf-8")):
            reject(f"bad hold evidence: {a}")
    return {"key": f"hold|{name}|{','.join(sorted(ids))}", "type": "hold", "test": name,
            "requirement_ids": ids, "disposition": p["disposition"],
            "explanation": p["explanation"].strip(), "evidence": anchors}


RECORDS = {"check": check_record, "group": group_record, "hold": hold_record}
# Subcommand -> proposal type.
COMMANDS = {"add": "check", "group": "group", "hold": "hold"}


def append(out: Path, record: dict) -> None:
    if record["key"] in {p["key"] for p in read_jsonl(out)}:
        reject(f"duplicate proposal key {record['key']} in {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"OK {record['key']}")


def cmd_scope(args):
    state = State()
    ids = json.loads(Path(args.assignment).read_text())["requirement_ids"]
    touched = defaultdict(set)
    for out in args.out or []:
        for p in read_jsonl(Path(out)):
            for rid in ([p["requirement_id"]] if "requirement_id" in p else p["requirement_ids"]):
                touched[rid].add(p["type"])
    for rid in ids:
        r = state.rows[rid]
        status = "MAPPED" if r["checks"] else "open"
        if touched.get(rid):
            status += "+" + "/".join(sorted(touched[rid]))
        print(f"{rid}\t{r['kind']}\t{status}\tcandidates={len(state.candidates(r))}\t"
              f"{r['behavior'][:110]}")
    print(f"# {len(ids)} assigned; {sum(not state.rows[i]['checks'] for i in ids)} still open")


def cmd_req(args):
    state = State()
    for rid in args.ids:
        r = state.rows.get(rid) or reject(f"unknown requirement {rid}")
        print(f"== {rid}  clause {r['clause']}  kind={r['kind']}  modality={r.get('modality')}")
        print(f"behavior:   {r['behavior']}")
        print(f"acceptance: {r['acceptance']}")
        print(f"source:     {r.get('source_spans')}  ({r['source_note']})")
        if r.get("interpretation_issue"):
            print(f"INTERPRETATION ISSUE (cannot map): {r['interpretation_issue']}")
        if r["checks"]:
            print(f"ALREADY MAPPED by: {[c['test'] for c in r['checks']]}")
        candidates = state.candidates(r)
        print(f"candidate tests ({len(candidates)}; cite {r['clause']}, same positive/negative kind):")
        for name in candidates:
            notes = []
            if (name, rid) in state.holds:
                notes.append("HELD: " + " / ".join(d["explanation"][:160]
                                                   for d in state.holds[(name, rid)]))
            if (name, rid) in state.withdrawn:
                notes.append("WITHDRAWN by an earlier audit")
            if name in BLOCKED_TESTS:
                notes.append("BLOCKED: " + BLOCKED_TESTS[name])
            print(f"  {name}" + ("   <-- " + " | ".join(notes) if notes else ""))
        print()


def cmd_test(args):
    state = State()
    name = args.test
    t = state.tests.get(name) or reject(f"not a suite test: {name}")
    test = ROOT / name
    print(f"== {name}")
    for k, v in suite_results.header(test).items():
        print(f"  :{k}: {v}")
    print("input files (evidence must come from these):")
    for p in suite_results.input_files(test):
        print(f"  {p.relative_to(ROOT).as_posix()}")
    if name in BLOCKED_TESTS:
        print(f"BLOCKED: {BLOCKED_TESTS[name]}")
    print(f"registered links: {t['registered_requirement_ids']}")
    mine = [(rid, d) for (tn, rid), ds in state.holds.items() if tn == name for d in ds]
    if mine:
        print("existing scoped holds on this test (do not override):")
        for rid, d in mine:
            print(f"  {rid}: [{d['disposition']}] {d['explanation']}")
    open_ids = [rid for rid in t["unapproved_candidate_ids"] if not state.rows[rid]["checks"]]
    print(f"unmapped candidates ({len(open_ids)}):")
    for rid in open_ids:
        flag = " HELD" if (name, rid) in state.holds else ""
        flag += " WITHDRAWN" if (name, rid) in state.withdrawn else ""
        print(f"  {rid}{flag}: {state.rows[rid]['behavior'][:120]}")


def cmd_propose(args):
    append(Path(args.out), RECORDS[COMMANDS[args.cmd]](State(), json.load(sys.stdin)))


def cmd_show(args):
    out = Path(args.out)
    verdicts = {v["key"]: v for v in read_jsonl(out.with_name(out.name + ".verdicts.jsonl"))}
    for p in read_jsonl(out):
        v = verdicts.get(p["key"])
        print(f"{p['key']}  " + (f"[{v['verdict']}: {v['reason'][:80]}]" if v else "[no verdict]"))


def cmd_verdict(args):
    out = Path(args.out)
    if args.key not in {p["key"] for p in read_jsonl(out)}:
        reject(f"no proposal with key {args.key} in {out}")
    if len(args.reason.strip()) < 15:
        reject("give a concrete reason (>= 15 chars)")
    record = {"key": args.key, "verdict": "accept" if args.accept else "reject",
              "reason": args.reason.strip(), "verifier": args.verifier}
    with out.with_name(out.name + ".verdicts.jsonl").open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"OK {record['verdict']} {args.key}")


def cmd_testverdict(args):
    if not (ROOT / args.test).is_file():
        reject(f"no such test {args.test}")
    if len(args.reason.strip()) < 15:
        reject("give a concrete reason (>= 15 chars)")
    record = {"test": args.test, "verdict": "ok" if args.ok else "defective",
              "reason": args.reason.strip(), "verifier": args.verifier}
    with Path(args.out).open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"OK {record['verdict']} {args.test}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scope")
    s.add_argument("assignment")
    s.add_argument("--out", action="append")
    s.set_defaults(fn=cmd_scope)
    s = sub.add_parser("req")
    s.add_argument("ids", nargs="+")
    s.set_defaults(fn=cmd_req)
    s = sub.add_parser("test")
    s.add_argument("test")
    s.set_defaults(fn=cmd_test)
    for name in COMMANDS:
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.set_defaults(fn=cmd_propose)
    s = sub.add_parser("show")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_show)
    for name, choices, fn in (("verdict", ("accept", "reject"), cmd_verdict),
                              ("testverdict", ("ok", "defective"), cmd_testverdict)):
        s = sub.add_parser(name)
        s.add_argument("--out", required=True)
        s.add_argument("--key" if name == "verdict" else "--test", required=True)
        g = s.add_mutually_exclusive_group(required=True)
        for choice in choices:
            g.add_argument(f"--{choice}", action="store_true")
        s.add_argument("--reason", required=True)
        s.add_argument("--verifier", default="verifier")
        s.set_defaults(fn=fn)
    args = ap.parse_args()
    try:
        args.fn(args)
    except Rejected as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
