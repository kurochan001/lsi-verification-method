from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
SPI=load_example('local-spi')


class SpiTest(unittest.TestCase):
    def test_all_modes_and_dividers_are_independent_configurations(self):
        self.assertEqual(len(SPI.CONFIGS),8)
        self.assertEqual({(p['CPOL'],p['CPHA'],p['HALF_DIV']) for p in SPI.CONFIGS.values()},
                         {(p,h,d) for p in (0,1) for h in (0,1) for d in (2,4)})

    def test_random_reproducibility_and_recovery(self):
        a=SPI.random_vectors(17,300)
        self.assertEqual(a,SPI.random_vectors(17,300))
        self.assertNotEqual(a,SPI.random_vectors(18,300))
        self.assertTrue(any(r[0]==1 for r in a))
        self.assertEqual(a[-1],[0,0x96,0x69,0,0])
        self.assertTrue(all(0<=r[1]<=255 and 0<=r[2]<=255 for r in a))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_rtl_all_modes_mutations_reset_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-spi',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,SPI.CONFIGS,16,48)
            for name in SPI.CONFIGS:
                counts=read_json(out/f'{name}-boundaries/result.json')['counts']
                self.assertEqual(counts,dict(transfers=7,aborts=1))


    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_demo_faults_cannot_pass_as_normal_rtl(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                with self.subTest(mutation=mutation):
                    out=Path(tmp)/f'm{mutation}'
                    p=run_example('local-spi',out,'--configuration','mode0-div2','--iterations','2','--demo-bug',str(mutation))
                    self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                    self.assertFalse(read_json(out/'summary.json')['success'])
                    self.assertEqual(read_json(out/'mode0-div2-boundaries'/'result.json')['status'],'fail')


if __name__=='__main__':unittest.main()
