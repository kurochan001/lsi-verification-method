"""Checks of tools/matching_kit against the current ledgers: a proposal that
validate() would refuse is refused when it is proposed, and the partitions
keep each section in one file."""

# Local revision (2026-10-26): CLI regressions for versioned acceptance and merge.

import json
import shutil
import subprocess
import sys
import tempfile
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


class ApprovalSnapshots(unittest.TestCase):
    """Exercise acceptance and merge in a small, isolated upstream layout."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for directory in ("tools/matching_kit", "coverage", "tests/ch6", "work"):
            (self.root / directory).mkdir(parents=True)
        for name in ("propose.py", "merge.py", "withdrawn-20261023.json"):
            shutil.copy2(Path(propose.__file__).parent / name,
                         self.root / "tools/matching_kit" / name)
        for name in ("suite_results.py", "behavior_coverage.py"):
            shutil.copy2(Path(propose.suite_results.__file__).parent / name,
                         self.root / "tools" / name)
        self.test_names = [f"tests/ch6/test_{letter}.sv" for letter in ("a", "b")]
        for name in self.test_names:
            path = self.root / name
            path.write_text('/*\n:lrm: 1800-2023 6\n'
                            f':expected_stdout: @{path.stem}.expected\n'
                            ':files: helper.svh\n*/\n`include "helper.svh"\n'
                            f'module {path.stem};\ninteger value;\ninitial begin\n'
                            'value = 1;\n$display("value=%0d", value);\nend\nendmodule\n')
            path.with_suffix(".expected").write_text("value=1\n")
        (self.root / "tests/ch6/helper.svh").write_text("// original helper\n")
        self.ids = ["SV2023-6-REVIEW-A", "SV2023-6-REVIEW-B"]
        self.registry = dict(schema=1, requirements=[
            dict(id=rid, clause="6", kind="normal", behavior="Displays one",
                 acceptance="Output equals one", source_note="Isolated fixture", checks=[])
            for rid in self.ids])
        self.save("coverage/behaviors.json", self.registry)
        sections = [dict(id=n, title="Fixture", pdf_page=1, kind="normative",
                         review="complete" if n == "6" else "no_behavior",
                         review_note="Isolated fixture", reviewed_on="2026-10-26")
                    for n in [*map(str, range(1, 42)), *"ABCDEFGHIJKLMNOPQ"]]
        self.save("coverage/standard-sections.json",
                  dict(schema=1, source=dict(pdf_pages=1), sections=sections))
        self.save("coverage/test-matching-reviews.json", dict(reviews=[]))
        self.save("coverage/test-matching.json", dict(tests=[]))
        self.out = self.root / "work/proposals.jsonl"

    def save(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def invoke(self, script, *args, body=None, code=0):
        result = subprocess.run(
            [sys.executable, str(self.root / "tools/matching_kit" / script), *map(str, args)],
            input=json.dumps(body) if body is not None else None,
            capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result.stdout

    def prepare(self, kind="check"):
        def member(name):
            return dict(test=name, observation="Assign one and compare the displayed value.",
                        evidence=[dict(file=name, contains='$display("value=%0d", value);'),
                                  dict(file=str(Path(name).with_suffix(".expected")),
                                       contains="value=1")])
        proposal = dict(requirement_id=self.ids[0],
                        rationale="A different assigned value changes the compared output.")
        if kind == "check":
            proposal.update(member(self.test_names[0]))
        elif kind == "group":
            proposal.update(group_id="pair", members=[member(n) for n in self.test_names],
                            collective_observation="Both test observations are required together.")
        else:
            proposal = dict(test=self.test_names[0], requirement_ids=self.ids,
                            disposition="partial_observation",
                            explanation="These inputs do not observe all the required conditions.",
                            evidence=member(self.test_names[0])["evidence"])
        self.invoke("propose.py", "add" if kind == "check" else kind,
                    "--out", self.out, body=proposal)
        self.key = json.loads(self.out.read_text())["key"]
        self.accept()

    def accept(self):
        self.invoke("propose.py", "verdict", "--out", self.out, "--key", self.key,
                    "--accept", "--reason", "Independently reviewed the current inputs.")

    def merge(self, *, code=0, dry_run=False):
        return self.invoke("merge.py", self.root / "work", "--reviewer", "fixture-verifier",
                           "--date", "2026-10-26", *(["--dry-run"] if dry_run else []), code=code)

    def assert_stale_merge(self):
        before = {p: p.read_bytes() for p in (self.root / "coverage").iterdir()}
        self.assertIn("[stale:", self.invoke("propose.py", "show", "--out", self.out))
        self.assertIn("SKIP", self.merge(code=1, dry_run=True))
        self.assertIn("SKIP", self.merge(code=1))
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertFalse((self.root / "work/merged-log.json").exists())

    def test_unchanged_approvals_merge_and_remain_idempotent(self):
        self.prepare()
        self.assertIn("applied=1", self.merge())
        registry = (self.root / "coverage/behaviors.json").read_bytes()
        self.assertIn("applied=0", self.merge())
        self.assertEqual(registry, (self.root / "coverage/behaviors.json").read_bytes())

    def test_changed_stimulus_output_or_helper_requires_new_review(self):
        self.prepare()
        for name, before, after in (
            (self.test_names[0], "value = 1;", "value = 2;"),
            (str(Path(self.test_names[0]).with_suffix(".expected")), "value=1\n", "value=1\nextra\n"),
            ("tests/ch6/helper.svh", "original helper", "changed helper"),
        ):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_text()
                path.write_text(original.replace(before, after))
                self.assert_stale_merge()
                path.write_text(original)

    def test_changed_requirement_contract_or_source_requires_new_review(self):
        self.prepare()
        for field, value in (("acceptance", "Output equals two"),
                             ("source_spans", [dict(clause="6", blocks=["B002"])])):
            with self.subTest(field=field):
                original = (self.root / "coverage/behaviors.json").read_text()
                registry = json.loads(original)
                registry["requirements"][0][field] = value
                self.save("coverage/behaviors.json", registry)
                self.assert_stale_merge()
                (self.root / "coverage/behaviors.json").write_text(original)

    def test_group_approval_covers_every_member(self):
        self.prepare("group")
        path = self.root / self.test_names[1]
        original = path.read_text()
        path.write_text(original.replace("value = 1;", "value = 2;"))
        self.assert_stale_merge()
        path.write_text(original)
        self.assertIn("applied=1", self.merge())

    def test_hold_approval_covers_every_requirement(self):
        self.prepare("hold")
        registry = json.loads(json.dumps(self.registry))
        registry["requirements"][1]["acceptance"] = "Output equals two"
        self.save("coverage/behaviors.json", registry)
        self.assert_stale_merge()
        self.save("coverage/behaviors.json", self.registry)
        self.assertIn("applied=1", self.merge())

    def test_edited_proposal_does_not_inherit_old_acceptance(self):
        self.prepare()
        proposal = json.loads(self.out.read_text())
        proposal["rationale"] = "A replacement rationale that has not been independently reviewed."
        self.out.write_text(json.dumps(proposal) + "\n")
        self.assert_stale_merge()

    def test_one_stale_approval_blocks_other_accepted_proposals(self):
        self.prepare()
        proposal = json.loads(self.out.read_text())
        proposal["requirement_id"] = self.ids[1]
        proposal["test"] = self.test_names[1]
        for anchor in proposal["evidence"]:
            anchor["file"] = anchor["file"].replace("test_a", "test_b")
        self.invoke("propose.py", "add", "--out", self.out, body=proposal)
        self.key = json.loads(self.out.read_text().splitlines()[-1])["key"]
        self.accept()
        path = self.root / self.test_names[0]
        path.write_text(path.read_text().replace("value = 1;", "value = 2;"))
        self.assert_stale_merge()

    def test_legacy_acceptance_requires_independent_review_again(self):
        self.prepare()
        verdicts = self.out.with_name(self.out.name + ".verdicts.jsonl")
        verdict = json.loads(verdicts.read_text())
        verdict.pop("review_snapshot")
        verdicts.write_text(json.dumps(verdict) + "\n")
        self.assert_stale_merge()
        self.accept()
        self.assertIn("applied=1", self.merge())

    def test_reacceptance_after_reviewing_changed_inputs_allows_merge(self):
        self.prepare()
        path = self.root / self.test_names[0]
        path.write_text(path.read_text() + "// Independently reviewed additional comment.\n")
        self.assert_stale_merge()
        self.accept()
        self.assertIn("applied=1", self.merge())


if __name__ == "__main__":
    unittest.main()
