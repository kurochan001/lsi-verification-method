import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('native_test',Path(__file__).resolve().parents[1]/'runner.py');S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)

class NativeTests(unittest.TestCase):
    def test_counts_require_exact_unique_complete_inventory(self):
        good='COUNT accepted=4\nCOUNT retired=3\nCOUNT cancelled=1\n'
        expected=dict(accepted=4,retired=3,cancelled=1);S.counts(good,expected)
        for text in ('',good+'COUNT accepted=4\n',good+'COUNT extra=0\n',good.replace('retired=3','retired=2'),good.replace('accepted=4','accepted=0x4')):
            with self.subTest(text=text),self.assertRaises(ValueError):S.counts(text,expected)

    def test_build_failure_cannot_be_an_expected_negative_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks=[];e=SimpleNamespace(out=Path(tmp),args=SimpleNamespace(timeout=1),check=lambda *args:checks.append(args))
            sim=S.Native(e,'unused',[],[])
            result=sim.execute('case',dict(execution=dict(returncode=None,error='missing compiler')),[],{},1,'CPP_DATA')
            self.assertEqual(result['status'],'error');self.assertFalse(checks[0][1])

    def test_completion_without_waveform_is_not_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks=[];e=SimpleNamespace(out=Path(tmp),args=SimpleNamespace(timeout=1),check=lambda *args:checks.append(args))
            sim=S.Native(e,'unused',[],[])
            def execute(command,log,*args):
                Path(log).write_text('COUNT retired=1\nRESULT PASS checks=1\n')
                return dict(command=command,returncode=0,error=None,seconds=0)
            with patch.object(S.E.P,'execute',side_effect=execute):
                result=sim.execute('case',dict(binary='fake',execution=dict(returncode=0,error=None)),[],dict(retired=1),1)
            self.assertEqual(result['status'],'error');self.assertFalse(checks[0][1])

if __name__=='__main__':unittest.main()
