import hashlib
import importlib.util
import json
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

    def execute_with_log(self,log,expected,validator=None):
        with tempfile.TemporaryDirectory() as tmp:
            checks=[];e=SimpleNamespace(out=Path(tmp),args=SimpleNamespace(timeout=1),check=lambda *args:checks.append(args))
            def execute(command,path,*args):
                Path(path).write_text(log);Path(command[-2]).write_text('$enddefinitions\n');Path(command[-1]).write_text('a\n1\n')
                return dict(command=command,returncode=0,error=None,seconds=0)
            with patch.object(S.E.P,'execute',side_effect=execute):
                return S.Native(e,'unused',[],[]).execute('case',dict(binary='fake',execution=dict(returncode=0,error=None)),[],expected,1,validator=validator),checks[0][1]

    def test_complete_execution_passes_only_with_exact_counts_and_validator(self):
        log='COUNT retired=1\nRESULT PASS checks=1\n'
        self.assertEqual(self.execute_with_log(log,dict(retired=1))[0]['status'],'pass')
        result,passed=self.execute_with_log(log,dict(retired=2));self.assertEqual(result['status'],'error');self.assertFalse(passed)
        def reject(directory):raise ValueError('analogue trace differs')
        result,passed=self.execute_with_log(log,dict(retired=1),reject);self.assertEqual((result['status'],result['message']),('error','analogue trace differs'));self.assertFalse(passed)

    def execute_case(self,log,code=0,wave='$enddefinitions $end\n',csv='time,value\n0,1\n',expected=None,**options):
        """One execution whose stand-in binary leaves this log, exit code, waveform and sampled trace; returns the record and the check verdict."""
        with tempfile.TemporaryDirectory() as tmp:
            checks=[];e=SimpleNamespace(out=Path(tmp),args=SimpleNamespace(timeout=1),check=lambda *args:checks.append(args))
            def execute(command,path,*args):
                Path(path).write_text(log)
                for target,text in ((command[-2],wave),(command[-1],csv)):
                    if text is not None:Path(target).write_text(text)
                return dict(command=command,returncode=code,error=None,seconds=0)
            with patch.object(S.E.P,'execute',side_effect=execute):
                result=S.Native(e,'unused',[],[]).execute('case',dict(binary='fake',execution=dict(returncode=0,error=None)),[],dict(retired=1) if expected is None else expected,1,**options)
            self.assertEqual(json.loads((Path(tmp)/'case/result.json').read_text())['status'],result['status']);self.assertEqual(checks[0][0],'case')
            return result,checks[0][1]
    PASSED='COUNT retired=1\nCOVER goal/a\nRESULT PASS checks=1\n';DETECTED='COVER goal/a\nCHECK_FAIL CPP_DATA\n'

    def test_a_detected_failure_needs_its_waveform_and_sampled_trace(self):
        result,passed=self.execute_case(self.DETECTED,1,label='CPP_DATA');self.assertEqual(result['status'],'detected');self.assertTrue(passed)
        for name,files in (('no waveform',dict(wave=None)),('waveform without definitions',dict(wave='$scope module top $end\n')),('no sampled trace',dict(csv=None)),('sampled trace without a row',dict(csv='time,value\n'))):
            result,passed=self.execute_case(self.DETECTED,1,label='CPP_DATA',**files)
            with self.subTest(name):self.assertEqual((result['status'],result['message']),('error','missing waveform or sampled trace'));self.assertFalse(passed)

    def test_a_pass_needs_a_complete_waveform_and_a_sampled_trace_with_a_row(self):
        result,passed=self.execute_case(self.PASSED);self.assertEqual((result['status'],result['message']),('pass','1 completed checks'));self.assertTrue(passed)
        for name,files in (('waveform without definitions',dict(wave='$scope module top $end\n')),('no sampled trace',dict(csv=None)),('empty sampled trace',dict(csv='')),('sampled trace without a row',dict(csv='time,value\n'))):
            result,passed=self.execute_case(self.PASSED,**files)
            with self.subTest(name):self.assertEqual((result['status'],result['message'],result['coverage']),('error','missing waveform or sampled trace',[]));self.assertFalse(passed)

    def test_coverage_is_credited_only_from_a_passing_run_that_asks_for_credit(self):
        self.assertEqual(self.execute_case(self.PASSED)[0]['coverage'],['goal/a'])
        result,passed=self.execute_case(self.PASSED,credited=False);self.assertEqual((result['status'],result['coverage']),('pass',[]));self.assertTrue(passed)
        def reject(directory):raise ValueError('analogue trace differs')
        for name,status,arguments,options in (('detected','detected',(self.DETECTED,1),dict(label='CPP_DATA')),('failed','fail',(self.DETECTED,1),{}),('survived','fail',(self.PASSED,),dict(label='CPP_DATA')),
                                              ('wrong counts','error',(self.PASSED,),dict(expected=dict(retired=2))),('rejected by its validator','error',(self.PASSED,),dict(validator=reject))):
            result,passed=self.execute_case(*arguments,**options)
            with self.subTest(name):self.assertEqual((result['status'],result['coverage']),(status,[]));self.assertEqual(passed,status=='detected')

    def test_probes_require_both_tools_to_exit_zero_and_the_pinned_verilator_version(self):
        version='Verilator 5.052 2026-01-01 rev v5.052\n';fine=dict(returncode=0,error=None)
        def probe(text=version,verilator=fine,cxx=fine):
            with tempfile.TemporaryDirectory() as tmp:
                e=SimpleNamespace(out=Path(tmp),args=SimpleNamespace(timeout=1,verilator='fake-verilator',cxx='fake-c++'))
                def execute(command,log,*args):
                    Path(log).write_text(text if command[0]=='fake-verilator' else 'c++ 1.0\n');return dict(verilator if command[0]=='fake-verilator' else cxx,command=command,seconds=0)
                with patch.object(S.E.P,'execute',side_effect=execute):good,results=S.Native(e,'unused',[],[]).probes()
                self.assertEqual(json.loads((Path(tmp)/'tools.json').read_text()),results);self.assertEqual([r['command'] for r in results.values()],[['fake-verilator','--version'],['fake-c++','--version']]);return good
        self.assertIs(probe(),True)
        for name,options in (('older version',dict(text='Verilator 5.040 2025-08-30 rev v5.040\n')),('longer version number',dict(text='Verilator 5.0521 2026-01-01\n')),('version alone',dict(text='Verilator 5.052')),
                             ('text before the version',dict(text='warning: old cache\n'+version)),('text after the version',dict(text=version+'%Error: internal\n')),('empty',dict(text='')),
                             ('verilator exit status',dict(verilator=dict(returncode=1,error=None))),('verilator not run',dict(verilator=dict(returncode=None,error='missing'))),
                             ('compiler exit status',dict(cxx=dict(returncode=1,error=None))),('compiler not run',dict(cxx=dict(returncode=None,error='missing')))):
            with self.subTest(name):self.assertIs(probe(**options),False)

    def test_source_freshness_fails_on_changed_or_missing_recorded_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);source=out/'source.txt';source.write_text('original');checks=[]
            (out/'manifest.json').write_text(json.dumps(dict(source_sha256={str(source):hashlib.sha256(b'original').hexdigest()})))
            e=SimpleNamespace(out=out,check=lambda *args:checks.append(args))
            S.fresh(e);source.write_text('changed');S.fresh(e);source.unlink();S.fresh(e);S.fresh(SimpleNamespace(out=out/'none',check=e.check),['tool changed'])
            self.assertEqual([c[1] for c in checks],[True,False,False,False])

if __name__=='__main__':unittest.main()
