from pathlib import Path
import json, subprocess, sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

P = load_example('local-ai-regression')


class AggregateTests(unittest.TestCase):
    def test_each_child_summary_form_is_accepted_when_complete(self):
        self.assertTrue(P.child_success(dict(success=True, complete=True, planned=6, results=6)))
        self.assertTrue(P.child_success(dict(success=True, planned=2, results=[
            dict(id='proof', outcome='pass'), dict(id='mutation', outcome='detected')])))
        self.assertTrue(P.child_success(dict(success=True, complete=True, planned=1,
                                             results=[dict(id='mp-lint', status='pass')])))

    def test_missing_incomplete_or_failed_children_are_rejected(self):
        for summary in (None, [], True, {}, dict(success=True, complete=True, planned=0, results=0),
                        dict(success=True, complete=False, planned=6, results=6),
                        dict(success=True, complete=True, planned=6, results=5),
                        dict(success=True, planned=1, results=[dict(id='proof', outcome='error')]),
                        dict(success=True, complete=False, planned=1, results=[dict(id='lint', status='pass')]),
                        dict(success=True, complete=True, planned=1, results=[dict(id='lint', status='fail')])):
            with self.subTest(summary=summary):
                self.assertFalse(P.child_success(summary))

    def test_duplicate_missing_or_malformed_result_ids_are_rejected(self):
        good = dict(id='check', outcome='pass')
        for rows in ([good, dict(good)], [dict(outcome='pass')], [dict(good, id='')], [dict(good, id=' ')],
                     ['pass'], [None]):
            with self.subTest(rows=rows):
                self.assertFalse(P.child_success(dict(success=True, complete=True, planned=len(rows), results=rows)))

    def test_stages_cover_every_child_once(self):
        self.assertEqual(P.STAGES['all'], P.SIMULATIONS + P.FORMALS + P.VERILATOR)
        self.assertEqual(len(set(P.STAGES['all'])), 6)

    def test_missing_child_python_fails_and_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = subprocess.run([sys.executable, P.__file__, '--stage', 'simulation',
                                     '--python', str(Path(tmp) / 'absent'), '--out', str(out)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            summary = json.loads((out / 'summary.json').read_text())
            self.assertFalse(summary['success'])
            self.assertEqual([r['id'] for r in summary['results']], P.SIMULATIONS)
            (out / 'keep').write_text('keep')
            result = subprocess.run([sys.executable, P.__file__, '--out', str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual((out / 'keep').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
