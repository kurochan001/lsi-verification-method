from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import reference as R
import vectors as V
spec=importlib.util.spec_from_file_location('mxfp4_runner_test',HERE/'run.py')
RUN=importlib.util.module_from_spec(spec);spec.loader.exec_module(RUN)


class ImportedSources(unittest.TestCase):
    RECORD=json.loads((HERE/'upstream.json').read_text(encoding='utf-8'))

    @staticmethod
    def digest(path):
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_tracked_files_match_the_recorded_current_hashes(self):
        present={str(p.relative_to(HERE/'upstream')) for p in (HERE/'upstream').rglob('*') if p.is_file()}
        self.assertEqual(present,set(self.RECORD['local_sha256']))
        self.assertEqual(set(self.RECORD['files_sha256']),set(self.RECORD['local_sha256']))
        for name,expected in self.RECORD['local_sha256'].items():
            self.assertEqual(self.digest(HERE/'upstream'/name),expected,name)

    def test_every_file_that_differs_from_the_source_has_a_recorded_reason(self):
        source,local,changes=(self.RECORD[k] for k in ('files_sha256','local_sha256','local_changes'))
        self.assertEqual({name for name in local if local[name]!=source[name]},set(changes))
        for name,change in changes.items():
            self.assertIn(change['basis'],('git','record','record+git','none'),name)
            self.assertTrue(change['reason'].strip(),name)
        # A file with no record must say so instead of carrying an invented reason.
        self.assertEqual([n for n,c in changes.items() if c['basis']=='none'],['rtl/quant_encoder.sv'])
        self.assertTrue(all('理由の記録なし' in c['reason'] for c in changes.values() if c['basis']=='none'))


class NumericContract(unittest.TestCase):
    def test_all_midpoints_choose_even_encodings(self):
        midpoints=[Fraction(1,4),Fraction(3,4),Fraction(5,4),Fraction(7,4),Fraction(5,2),Fraction(7,2),Fraction(5)]
        for midpoint,code in zip(midpoints,[0,2,2,4,4,6,6]):
            for sign in [1,-1]:
                values=[R.fp32(sign*midpoint),0x40800000]+[0]*30
                self.assertEqual(R.encode(values)&15,code | (8 if sign<0 else 0))

    def test_rounding_is_per_block_not_at_end(self):
        pairs=[(V.block(2,139),V.block(2,139)),(V.block(),V.block()),(V.block(10,139),V.block(2,139))]
        acc=0
        for i,(a,b) in enumerate(pairs):acc=R.accumulate(acc,a,b,i==0)
        self.assertEqual(acc,0)
        self.assertEqual(R.fp32(Fraction(2**24)+1-2**24),0x3F800000)

    def test_subnormal_term_is_added_before_ftz(self):
        acc=R.accumulate(0,V.block(2,64),V.block(2,64),True)
        self.assertEqual(acc,0x00800000)
        result=R.accumulate(acc,V.block(10,63),V.block(2,64))
        self.assertEqual(result,0)
        self.assertEqual(R.fp32(R.power2(-127),gradual=True),0x00400000)

    def test_special_and_all_zero_encoder_blocks_are_canonical(self):
        for special in [0x7F800000,0xFF800000,0x7FC00001]:
            self.assertEqual(R.encode([special]+[0]*31),255<<128)
        self.assertEqual(R.encode([0x80000000,1,0x807FFFFF]+[0]*29),0)
        self.assertEqual(R.accumulate(R.INF,V.block(0,255),V.block()),R.QNAN)

    def test_all_256_element_products_are_present(self):
        rows=V.make_vectors(17,1)
        self.assertEqual({(r[3]&15,r[4]&15) for r in rows[:256]},
                         {(a,b) for a in range(16) for b in range(16)})
        self.assertEqual(rows,V.make_vectors(17,1))


class RunnerContract(unittest.TestCase):
    def test_compiler_failure_still_produces_failed_junit(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'result'
            completed=subprocess.run([sys.executable,str(HERE/'run.py'),'--verilator','/usr/bin/false',
                                      '--iterations','1','--stage','core','--out',str(out)],capture_output=True,text=True)
            self.assertEqual(completed.returncode,1,completed.stdout+completed.stderr)
            summary=json.loads((out/'summary.json').read_text())
            self.assertFalse(summary['success'])
            self.assertEqual(summary['planned'],19)
            self.assertTrue((out/'junit.xml').is_file())

    def test_exit_zero_does_not_override_failed_or_incomplete_checks(self):
        success={'returncode':0,'error':None}
        log=' tb_test : 10 checks, 0 errors\n *** PASS ***\n'
        self.assertTrue(RUN.upstream_result(success,log,'tb_test'))
        for invalid in ['',log+log,log+'[FAIL] mismatch\n',log.replace('10 checks','0 checks'),log.replace('0 errors','1 errors')]:
            self.assertFalse(RUN.upstream_result(success,invalid,'tb_test'))
        self.assertFalse(RUN.upstream_result({'returncode':1,'error':None},log,'tb_test'))
        self.assertFalse(RUN.upstream_result({'returncode':None,'error':'timeout'},log,'tb_test'))

    def test_requirement_checks_exist_in_execution_plan(self):
        checks=set(RUN.BENCHES)|set(RUN.MP_CHECKS)|{'rational-ftz','rational-gradual','rational-scale34','rational-nearfar'}
        catalog=json.loads((HERE/'requirements.json').read_text())
        self.assertEqual(len(catalog['requirements']),15)
        for requirement in catalog['requirements']:
            self.assertTrue(requirement['checks'])
            self.assertLessEqual(set(requirement['checks']),checks)


if __name__=='__main__':unittest.main()
