"""Check the review rules and the saved catalogue without running a simulator."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ai_review_under_test', HERE / 'run.py')
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)
CATALOG = json.loads((HERE / 'proposals.json').read_text(encoding='utf-8'))
ALL = sorted(RUN.REQUIREMENTS)
FINDINGS = {'requirement-omitted', 'collision-not-observed', 'mutation-survived', 'assertion-rejects-correct-rtl',
            'antecedent-unreachable', 'incorrect-rtl-passed', 'rtl-and-model-share-error', 'independent-check-disabled'}


def record(status='pass', returncode=0, rtl=0, model=0, sva_off=0, native=None, problems=()):
    counts = dict(cp_event=5, cp_collision=2, cp_obligation=5)
    counts.update(native or {})
    return dict(status=status, problems=list(problems), sva_off=sva_off, native=counts,
                oracle=dict(rtl_mismatches=rtl, model_mismatches=model),
                execution=dict(error=None, returncode=returncode))


def proposal(requirements=ALL):
    return dict(requirements=list(requirements))


class ReviewRules(unittest.TestCase):
    def test_a_clean_complete_proposal_has_no_finding(self):
        self.assertEqual(RUN.review(proposal(), record(), 'RESULT PASS checks=9\n'), [])

    def test_each_rule_fires_alone_on_its_own_evidence(self):
        self.assertEqual(RUN.review(proposal(ALL[:-1]), record(), ''), ['requirement-omitted'])
        self.assertEqual(RUN.review(proposal(), record(native=dict(cp_collision=0)), ''), ['collision-not-observed'])
        self.assertEqual(RUN.review(proposal(), record(), '', record()), ['mutation-survived'])
        self.assertEqual(RUN.review(proposal(), record(), '', record('fail', 1)), [])          # a killed mutant is fine
        self.assertEqual(RUN.review(proposal(), record(native=dict(cp_obligation=0)), ''), ['antecedent-unreachable'])
        self.assertEqual(RUN.review(proposal(), record(rtl=3), ''), ['incorrect-rtl-passed'])
        self.assertEqual(RUN.review(proposal(), record(rtl=3, model=3), ''),
                         ['incorrect-rtl-passed', 'rtl-and-model-share-error'])
        self.assertEqual(RUN.review(proposal(), record(rtl=3, model=2), ''), ['incorrect-rtl-passed'])
        self.assertEqual(RUN.review(proposal(), record(sva_off=1), ''), ['independent-check-disabled'])

    def test_a_false_assertion_failure_needs_the_single_label_and_a_correct_rtl(self):
        failed = record('fail', 1)
        self.assertEqual(RUN.review(proposal(), failed, 'CHECK_FAIL SVA_PAST\n'), ['assertion-rejects-correct-rtl'])
        self.assertEqual(RUN.review(proposal(), failed, 'CHECK_FAIL SVA_EVENT\n'), [])
        self.assertEqual(RUN.review(proposal(), failed, 'CHECK_FAIL SVA_PAST\nCHECK_FAIL SVA_PAST\n'), [])
        self.assertEqual(RUN.review(proposal(), failed, 'CHECK_FAIL SVA_PAST\nRESULT PASS checks=1\n'), [])
        self.assertEqual(RUN.review(proposal(), record('fail', 1, rtl=1), 'CHECK_FAIL SVA_PAST\n'), [])  # the RTL really is wrong

    def test_a_failed_or_problem_run_is_not_credited_as_a_pass(self):
        for bad in (record('fail', 1, rtl=3, model=3), record(rtl=3, model=3, problems=['missing log'])):
            self.assertEqual(RUN.review(proposal(), bad, ''), [])


class SavedCatalogue(unittest.TestCase):
    def test_catalogue_matches_the_runner_inventory(self):
        self.assertEqual(CATALOG['schema_version'], 1)
        self.assertEqual(set(CATALOG['requirements']), RUN.REQUIREMENTS)
        self.assertEqual({p['id'] for p in CATALOG['proposals']}, RUN.PROPOSALS)
        self.assertEqual(len(CATALOG['proposals']), 4)

    def test_every_proposal_expects_known_findings_and_every_finding_is_used(self):
        used = set()
        for item in CATALOG['proposals']:
            self.assertTrue(item['expected_findings'], item['id'])
            self.assertEqual(len(item['expected_findings']), len(set(item['expected_findings'])), item['id'])
            self.assertLessEqual(set(item['expected_findings']), FINDINGS, item['id'])
            self.assertLessEqual(set(item['requirements']), RUN.REQUIREMENTS, item['id'])
            self.assertLessEqual(set(item['flags']), {'mutation', 'model', 'sva_mode', 'sva_off'}, item['id'])
            used |= set(item['expected_findings'])
        self.assertEqual(used, FINDINGS)
        # Only the proposal that leaves a requirement out may omit the collision stimulus.
        self.assertEqual([p['id'] for p in CATALOG['proposals'] if p['omit_collision']], ['missing-condition'])
        self.assertEqual([p['id'] for p in CATALOG['proposals'] if set(p['requirements']) != RUN.REQUIREMENTS],
                         ['missing-condition'])


class CommandLine(unittest.TestCase):
    def run_cli(self, *options):
        return subprocess.run([sys.executable, str(HERE / 'run.py'), *options], capture_output=True, text=True, timeout=60)

    def test_invalid_limits_and_a_missing_tool_do_not_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_cli('--out', str(Path(tmp) / 'a'), '--build-timeout', '0').returncode, 2)
            self.assertEqual(self.run_cli('--out', str(Path(tmp) / 'b'), '--build-timeout', 'nan').returncode, 2)
            missing = self.run_cli('--out', str(Path(tmp) / 'c'), '--verilator', str(Path(tmp) / 'no-verilator'))
            self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
            summary = json.loads((Path(tmp) / 'c/summary.json').read_text())
            self.assertFalse(summary['success'])


if __name__ == '__main__':
    unittest.main()
