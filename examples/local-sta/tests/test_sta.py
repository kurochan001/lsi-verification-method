import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,run_example
P=load_example('local-sta')
C=json.loads(P.CONTRACT.read_text())
STA=P.ROOT/'artifacts/toolchains/opensta-build/sta'


def evidence():
    lines=['AUDIT constraints 1']
    for mode,values in [('max',C['corners']['fast']['setup']),('min',C['corners']['fast']['hold'])]:
        lines += [f'MEASURE {name} {mode} {value}' for name,value in zip(C['paths'],values)]
    return '\n'.join(lines+['RESULT STA PASS checks=6'])+'\n'


class StaTests(unittest.TestCase):
    def test_malformed_contract_cannot_remove_golden_checks(self):
        changes=[lambda d:d['corners']['fast'].update(setup=[]),
                 lambda d:d['corners']['slow'].update(hold=[0,float('nan'),0]),
                 lambda d:d.update(paths=['input','input','output']),
                 lambda d:d['corners'].pop('slow'),lambda d:d['corners']['fast'].update(period=0)]
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'contract.json'
            for change in changes:
                data=copy.deepcopy(C);change(data);path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):P.load_contract(path)

    def judge(self,log,**changes):
        case=dict(configuration='fast',mutation=0,expect='PASS',category='normal');case.update(changes)
        return P.judge(case,dict(error=None,returncode=0),log,C)[0]

    @unittest.skipUnless(STA.exists(),'build OpenSTA as described in README')
    def test_real_sta_two_corners_and_all_negative_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';r=run_example('local-sta',out,'--sta',str(STA.relative_to(P.ROOT)))
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            s=json.loads((out/'summary.json').read_text());self.assertTrue(s['success']);self.assertTrue(s['evidence_ok'])
            self.assertEqual(len(s['results']),10);self.assertEqual(sum(r['status']=='detected' for r in s['results']),8)
            j=ET.parse(out/'junit.xml').getroot();self.assertEqual(j.get('tests'),'11');self.assertEqual(j.get('errors'),'0')

    @unittest.skipUnless(STA.exists(),'build OpenSTA as described in README')
    def test_each_demo_fails_the_normal_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                out=Path(tmp)/str(mutation)
                r=run_example('local-sta',out,'--configuration','fast','--sta',str(STA),'--demo-bug',str(mutation))
                self.assertEqual(r.returncode,1,r.stdout+r.stderr)
                self.assertEqual(json.loads((out/'fast-normal/result.json').read_text())['status'],'fail')

    def test_missing_requested_tool_is_an_error_without_path_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';r=run_example('local-sta',out,'--sta',str(Path(tmp)/'absent'))
            self.assertEqual(r.returncode,1)
            s=json.loads((out/'summary.json').read_text());self.assertFalse(s['success']);self.assertFalse(s['evidence_ok'])
            self.assertTrue(all(r['status']=='error' for r in s['results']))

    def test_missing_path_or_completion_record_is_not_pass(self):
        self.assertEqual(self.judge(evidence()),'pass')
        for text in [evidence().replace('MEASURE internal max 1.05\n',''),evidence().replace('RESULT STA PASS checks=6','')]:
            self.assertEqual(self.judge(text),'error')

    def test_duplicate_nonfinite_and_inconsistent_verdict_are_rejected(self):
        for text in [evidence()+'MEASURE internal max 1.05\n',evidence().replace('1.05','NaN'),
                     evidence().replace('1.05','-1.05')]:self.assertEqual(self.judge(text),'error')

    def test_positive_but_wrong_slack_is_rejected_by_independent_contract(self):
        self.assertEqual(self.judge(evidence().replace('1.05','1.04')),'fail')

    def test_crash_cannot_be_counted_as_a_timing_violation(self):
        case=dict(configuration='fast',mutation=1,expect='STA_SETUP',category='mutation')
        self.assertEqual(P.judge(case,dict(error=None,returncode=1),'Error: invalid liberty\n',C)[0],'error')

    def test_false_path_on_a_different_path_is_not_intended_detection(self):
        log=evidence().replace('MEASURE input max 0.75','MISSING input max').replace('MEASURE input min 0.09','MISSING input min').replace('RESULT STA PASS','RESULT STA STA_PATH')
        case=dict(configuration='fast',mutation=4,expect='STA_PATH',category='mutation')
        self.assertEqual(P.judge(case,dict(error=None,returncode=1),log,C)[0],'error')


if __name__=='__main__':unittest.main()
