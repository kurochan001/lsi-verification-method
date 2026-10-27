import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
PATH=Path(__file__).resolve().parents[1]/'evidence.py'
spec=importlib.util.spec_from_file_location('search_support',PATH);P=importlib.util.module_from_spec(spec);spec.loader.exec_module(P)
class PlannedEvidenceTests(unittest.TestCase):
    def args(self,path):return SimpleNamespace(out=path,profile='smoke',seed=17)
    def test_missing_planned_check_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=P.Evidence('test',self.args(Path(tmp)/'out'),[],{},['first','second']);e.check('first',True,'ok')
            self.assertEqual(e.finish(),1);d=json.loads((e.out/'summary.json').read_text())
            self.assertFalse(d['complete']);self.assertEqual(d['planned'],2);self.assertEqual(d['results'][-1]['status'],'fail')
    def test_duplicate_and_unplanned_checks_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            e=P.Evidence('test',self.args(Path(tmp)/'out'),[],{},['first']);e.check('first',True,'ok')
            for name in ('first','other'):
                with self.assertRaises(ValueError):e.check(name,True,'bad')
    def test_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            args=self.args(Path(tmp)/'out');P.Evidence('test',args,[],{},['check'])
            with self.assertRaises(FileExistsError):P.Evidence('test',args,[],{},['check'])
if __name__=='__main__':unittest.main()
