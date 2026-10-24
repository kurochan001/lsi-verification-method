"""Checks of tools/matching_kit against the current ledgers: a proposal that
validate() would refuse is refused when it is proposed, and the partitions
keep each section in one file."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "matching_kit"))
import partition  # noqa: E402
import propose  # noqa: E402


class ProposeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.state = propose.State()

    def open_row(self, kind: str):
        """An open requirement of this kind and a test that cites its clause."""
        for r in self.state.rows.values():
            if r["checks"] or r.get("interpretation_issue") or r["kind"] != kind:
                continue
            candidates = self.state.candidates(r)
            if candidates:
                return r, candidates[0]
        self.skipTest(f"no open {kind} requirement with a candidate test")

    def proposal(self, rid: str, test: str, evidence: list) -> dict:
        return {"requirement_id": rid, "test": test, "evidence": evidence,
                "observation": "the stimulus and the values the expected output compares",
                "rationale": "a wrong implementation prints another value on that line"}

    def test_mapped_requirement_is_refused(self):
        row = next(r for r in self.state.rows.values() if r["checks"])
        p = self.proposal(row["id"], row["checks"][0]["test"], row["checks"][0]["evidence"])
        with self.assertRaisesRegex(propose.Rejected, "already mapped"):
            propose.check_record(self.state, p)

    def test_missing_anchor_is_refused(self):
        row, test = self.open_row("normal")
        fields = propose.suite_results.header(propose.ROOT / test)
        expected = fields.get("expected_stdout", "")
        out = (str(Path(test).parent / expected[1:]) if expected.startswith("@") else test)
        p = self.proposal(row["id"], test, [{"file": test, "contains": "no such text in the test"},
                                            {"file": out, "contains": "no such text either"}])
        with self.assertRaisesRegex(propose.Rejected, "not found verbatim"):
            propose.check_record(self.state, p)

    def test_test_that_does_not_cite_the_clause_is_refused(self):
        row, _ = self.open_row("normal")
        other = next(name for name, t in self.state.tests.items()
                     if row["clause"] not in t["cited_clauses"] and not t["negative_test"])
        p = self.proposal(row["id"], other, [{"file": other, "contains": "module"}])
        with self.assertRaisesRegex(propose.Rejected, "does not cite clause"):
            propose.check_record(self.state, p)

    def test_hold_needs_a_known_disposition(self):
        test = next(iter(self.state.tests))
        rid = next(iter(self.state.rows))
        p = {"test": test, "requirement_ids": [rid], "disposition": "maybe",
             "explanation": "a concrete missing observation of the requirement",
             "evidence": [{"file": test, "contains": "module"}]}
        with self.assertRaisesRegex(propose.Rejected, "disposition"):
            propose.hold_record(self.state, p)

    def test_withdrawn_links_are_known(self):
        withdrawn = json.loads(propose.WITHDRAWN.read_text())
        self.assertTrue(withdrawn)
        self.assertTrue({(c["test"], rid) for rid, c in withdrawn} <= self.state.withdrawn)


class PartitionChunks(unittest.TestCase):
    def test_sections_stay_whole(self):
        clause_of = {f"r{i}": c for i, c in enumerate(["1.1"] * 3 + ["1.2"] * 5 + ["2.1"] * 4)}
        groups = partition.chunks(sorted(clause_of), clause_of, target=4)
        self.assertEqual(sorted(i for g in groups for i in g), sorted(clause_of))
        for g in groups:
            for clause in {clause_of[i] for i in g}:
                self.assertTrue(all(clause_of[i] != clause for h in groups if h is not g for i in h))


if __name__ == "__main__":
    unittest.main()
