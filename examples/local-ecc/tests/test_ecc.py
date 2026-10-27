from itertools import combinations
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
ECC=load_example('local-ecc')


class EccTest(unittest.TestCase):
    def test_codebook_distance_and_known_encodings(self):
        self.assertEqual(len(ECC.CODEBOOK),256)
        self.assertEqual(ECC.CODEBOOK[0],0)
        self.assertEqual(ECC.CODEBOOK[1],0x1007)
        self.assertEqual(min((a^b).bit_count() for a,b in combinations(ECC.CODEBOOK.values(),2)),4)

    def test_all_error_patterns_have_correct_class_and_payload(self):
        rows=ECC.exhaustive_vectors()
        self.assertEqual(len(rows),23552)
        self.assertEqual(ECC.counts(rows),dict(clean=256,single=3328,double=19968,triple=0,four=0))
        for value,received,encoded,fixed,data,corrected,uncorrectable in rows:
            weight=(received^encoded).bit_count()
            self.assertEqual((corrected,uncorrectable),(int(weight==1),int(weight==2)))
            if weight<2:self.assertEqual((fixed,data),(encoded,value))

    def test_limits_are_miscorrection_and_undetected_error(self):
        triple=ECC.row(0,7)
        four=ECC.row(0,ECC.CODEBOOK[1])
        self.assertEqual(triple[4:], [1,1,0])
        self.assertEqual(four[4:], [1,0,0])
        self.assertNotEqual(triple[4],triple[0])
        self.assertEqual(ECC.CODEBOOK[1].bit_count(),4)

    def test_random_is_reproducible_and_within_guaranteed_error_weights(self):
        a=ECC.random_vectors(17,100)
        self.assertEqual(a,ECC.random_vectors(17,100))
        self.assertNotEqual(a,ECC.random_vectors(18,100))
        self.assertTrue(all((r[1]^r[2]).bit_count()<=2 for r in a))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_exhaustive_rtl_mutations_diagnostics_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-ecc',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,['hamming13-8'],97,8,diagnostics=2)
            r=read_json(out/'hamming13-8-exhaustive/result.json')
            self.assertEqual(r['counts']['double'],19968)
            for case,label in [('triple-limit','LIMIT triple/miscorrection'),('four-limit','LIMIT four/undetected')]:
                self.assertIn(label,(out/f'hamming13-8-{case}/simulation.log').read_text())


    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_demo_faults_cannot_pass_as_normal_rtl(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                with self.subTest(mutation=mutation):
                    out=Path(tmp)/f'm{mutation}'
                    p=run_example('local-ecc',out,'--configuration','hamming13-8','--iterations','2','--demo-bug',str(mutation))
                    self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                    self.assertFalse(read_json(out/'summary.json')['success'])
                    self.assertEqual(read_json(out/'hamming13-8-exhaustive'/'result.json')['status'],'fail')


if __name__=='__main__':unittest.main()
