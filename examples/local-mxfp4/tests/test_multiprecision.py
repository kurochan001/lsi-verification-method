from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import reference as R
import reference_mp as M
import vectors_mp as V
spec=importlib.util.spec_from_file_location('mp_runner_test',HERE/'run.py')
RUN=importlib.util.module_from_spec(spec);spec.loader.exec_module(RUN)


class MultiprecisionNumbers(unittest.TestCase):
    def test_e4m3_limits_and_nan_encodings(self):
        self.assertEqual(M.decode(0x7E,M.FP8),448)
        self.assertEqual(M.decode(0xFE,M.FP8),-448)
        self.assertEqual(M.decode(1,M.FP8),Fraction(1,512))
        self.assertEqual(M.decode(8,M.FP8),Fraction(1,64))
        self.assertEqual([c for c in range(256) if M.decode(c,M.FP8)==M.NAN],[0x7F,0xFF])

    def test_e4m3_half_lsb_binade_is_not_all_zero(self):
        half=R.fp32(R.power2(-10))
        values=[0x43E00000,half,half+1,R.fp32(3*R.power2(-11))]+[0]*28
        codes=R.unpack(M.encode8(values)[0],16,8)
        self.assertEqual(codes[:4],[0x7E,0,1,1])

    def test_e4m3_subnormal_midpoints_choose_even(self):
        for lower in range(15):
            value=(M.FP8_POSITIVE[lower]+M.FP8_POSITIVE[lower+1])/2
            for sign in [1,-1]:
                codes=R.unpack(M.encode8([0x43E00000,R.fp32(sign*value)]+[0]*30)[0],16,8)
                self.assertEqual(codes[1],(lower+(lower%2))|(128 if sign<0 else 0))

    def test_fp16_products_are_exact_at_both_extremes(self):
        self.assertEqual(M.product16(1,1),0x27800000) # 2^-48
        self.assertEqual(M.product16(0x7BFF,0x7BFF),0x4F7FC004)
        self.assertEqual(M.product16(0x7C00,0),R.QNAN)
        self.assertEqual(M.product16(0xFC00,0x3C00),0xFF800000)

    def test_fp16_cast_subnormal_ties_and_overflow(self):
        half=R.fp32(R.power2(-25))
        self.assertEqual(M.cast16(half),0)
        self.assertEqual(M.cast16(half+1),1)
        self.assertEqual(M.cast16(R.fp32(3*R.power2(-25))),2)
        self.assertEqual(M.cast16(half|0x80000000),0x8000)
        self.assertEqual(M.cast16(R.fp32(Fraction(65520))),0x7C00)
        self.assertEqual(M.cast16(R.fp32(Fraction(65519))),0x7BFF)

    def test_fp16_midpoints_use_code_parity_and_both_neighbors(self):
        samples=list(V.fp16_midpoint_samples())
        for bits,expected in samples:
            self.assertEqual(M.cast16(bits),expected,hex(bits))
        # Largest subnormal / smallest normal: just below, at, and above the tie.
        midpoint=R.fp32((M.decode(0x03FF,M.FP16)+M.decode(0x0400,M.FP16))/2)
        self.assertIn((midpoint-1,0x03FF),samples)
        self.assertIn((midpoint,0x0400),samples)
        self.assertIn((midpoint+1,0x0400),samples)

    def test_fp16_tree_is_balanced_not_a_left_fold(self):
        a=[0x6C00,0x3C00,0xEC00,0xBC00]+[0]*4
        b=[0x6C00,0x3C00,0x6C00,0x3C00]+[0]*4
        self.assertEqual(M.dot16(a,b),0)
        folded=0
        for x,y in zip(a,b):folded=M.add32(folded,M.product16(x,y))
        self.assertEqual(folded,0xBF800000)

    def test_fp8_block_rounding_is_a_separate_rounding_point(self):
        codes=[0x50,1]+[0]*30
        term=M.dot8(codes,codes,124,124)
        self.assertEqual(term,0x3F800000)
        acc=R.fp32(R.power2(-24))
        self.assertEqual(M.add32(acc,term),0x3F800000)
        self.assertEqual(R.fp32(1+2*R.power2(-24)),0x3F800001)

    def test_seeded_commands_and_input_geometry(self):
        commands=V.gemm_vectors(17,1,2,3,3)
        self.assertEqual(commands,V.gemm_vectors(17,1,2,3,3))
        for row in commands:
            if row[0]<2:
                count=(2 if row[0]==0 else 3)*3*{0:4,1:2,2:1}[row[1]]
                self.assertLess(row[2],count)


class MultiprecisionRunner(unittest.TestCase):
    def test_catalogue_scope_and_unknown_checks(self):
        catalog=json.loads((HERE/'requirements.json').read_text())
        included,outside=RUN.scoped_requirements(catalog,RUN.MP_CHECKS)
        self.assertEqual(len(included),6)
        self.assertEqual(len(outside),9)
        corrupt=json.loads(json.dumps(catalog));corrupt['requirements'][0]['checks']=['missing']
        with self.assertRaises(ValueError):RUN.scoped_requirements(corrupt,RUN.MP_CHECKS)

    def test_compiler_failure_is_not_an_extension_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'result'
            command=[sys.executable,str(HERE/'run.py'),'--stage','multiprecision','--verilator','/usr/bin/false','--iterations','1','--out',str(out)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            summary=json.loads((out/'summary.json').read_text())
            self.assertFalse(summary['success'])
            self.assertEqual(summary['planned'],8)
            self.assertTrue((out/'junit.xml').is_file())


if __name__=='__main__':unittest.main()
