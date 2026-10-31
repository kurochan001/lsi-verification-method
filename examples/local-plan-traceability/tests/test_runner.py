import importlib.util
import json
from pathlib import Path
import unittest
import tempfile
S=importlib.util.spec_from_file_location('plan_example',Path(__file__).resolve().parents[1]/'run.py');M=importlib.util.module_from_spec(S);S.loader.exec_module(M)
class AdapterPlanTests(unittest.TestCase):
    def test_all_six_assertions_have_source_item_and_native_covers(self):
        p=json.loads(M.PLAN.read_text());self.assertEqual(len(p['requirements']),6);self.assertEqual(len(p['items']),6)
        actual={item['checkers'][0]:set(item['goals']) for item in p['items']};self.assertEqual(actual,M.SVA.ASSERTION_COVERS)
        self.assertEqual({r['id'] for r in p['requirements']},{item['requirements'][0] for item in p['items']})
    def test_eleven_distinct_rejection_scenarios_are_planned(self):
        self.assertEqual(len(M.DIAGNOSTICS),11);self.assertIn('stale-artifact',M.DIAGNOSTICS);self.assertIn('checker-off',M.DIAGNOSTICS);self.assertIn('unpaired-goal',M.DIAGNOSTICS)
    def test_child_success_cannot_hide_missing_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            (directory/'manifest.json').write_text(json.dumps(dict(cases=[dict(id='case')],source_sha256={})))
            (directory/'summary.json').write_text(json.dumps(dict(success=True,complete=True,planned=1,results=0)))
            with self.assertRaisesRegex(ValueError,'fixed plan'):M.normalize(directory,json.loads(M.PLAN.read_text()))
    def test_child_source_inventory_cannot_omit_the_checker(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            (directory/'manifest.json').write_text(json.dumps(dict(cases=[dict(id='case')],source_sha256={})))
            (directory/'summary.json').write_text(json.dumps(dict(success=True,complete=True,planned=1,results=1)))
            (directory/'build.json').write_text(json.dumps(dict(error=None,returncode=0,command=['verilator','--assert'])))
            with self.assertRaisesRegex(ValueError,'source inventory'):M.normalize(directory,json.loads(M.PLAN.read_text()))
    def test_input_changed_while_child_was_running_invalidates_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);source=directory/'spec.md';source.write_text('reviewed revision')
            snapshot={'spec.md':M.V.digest(source)};M.verify_snapshot(snapshot,directory)
            source.write_text('changed before evidence conversion')
            with self.assertRaisesRegex(ValueError,'during execution'):M.verify_snapshot(snapshot,directory)
if __name__=='__main__':unittest.main()
