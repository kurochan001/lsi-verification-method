import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
HERE=Path(__file__).resolve().parents[1];S=importlib.util.spec_from_file_location('change_test',HERE/'run.py');P=importlib.util.module_from_spec(S);S.loader.exec_module(P)
class ChangeTests(unittest.TestCase):
    def test_revision_changes_only_reviewed_priority_expressions(self):
        r1,t1=P.prepared(1);r2,t2=P.prepared(2)
        self.assertEqual(r2,r1.replace(P.RTL_OLD,P.RTL_NEW));self.assertEqual(t2,t1.replace(P.MODEL_OLD,P.MODEL_NEW));self.assertEqual(P.prepared(2,True)[1],t1)
    def test_changed_upstream_adapter_is_rejected(self):
        for text in ('missing',P.RTL_OLD*2):
            with self.assertRaises(ValueError):P.replace_once(text,P.RTL_OLD,P.RTL_NEW)
    def test_every_revision_covers_all_waits_and_eight_collision_goals(self):
        plan=json.loads((HERE/'plan.json').read_text());self.assertEqual(len(plan['tests']),6)
        for item in plan['items']:
            self.assertEqual(set(item['goals']),P.GOALS);self.assertEqual(set(item['configurations']),{'wait0','wait1','wait3'})
    def test_native_measurement_requires_rtl_line_counters(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'coverage.dat';p.write_text('# no counters\n')
            with self.assertRaises(ValueError):P.native_counts(p,'',Path(d)/'rtl.sv')
    def test_checked_code_contains_no_mutation_of_the_original_sources(self):
        r,t=P.prepared(1);P.prepared(2)
        self.assertEqual(P.REGS.read_text(),r);self.assertEqual(P.TB.read_text(),t)
if __name__=='__main__':unittest.main()
