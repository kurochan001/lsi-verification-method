from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
I2C=load_example('local-i2c')


class I2cTest(unittest.TestCase):
    def test_nacks_preserve_value_and_reset_discards_partial_write(self):
        rows,counts=I2C.reference([[0,0x42,0xa5,0],[3,0x43,0x11,0],[4,0x42,0x22,0],
                                   [2,0x42,0,0],[5,0x42,0xff,0],[2,0x42,0,0]])
        self.assertEqual([r[-1] for r in rows],[0xa5,0xa5,0xa5,0xa5,0,0])
        self.assertEqual(counts,dict(writes=1,reads=2,target_nacks=2,resets=1,stretches=0))

    def test_stretch_count_includes_only_acknowledged_target_responses(self):
        commands=[[m,0x43 if m==3 else 0x42,0x55,20] for m in range(6)]
        _,counts=I2C.reference(commands)
        self.assertEqual(counts['stretches'],8)
        self.assertEqual(counts['target_nacks'],2)

    def test_random_transactions_are_reproducible_and_end_in_recovery(self):
        a=I2C.random_commands(17,300)
        self.assertEqual(a,I2C.random_commands(17,300))
        self.assertNotEqual(a,I2C.random_commands(18,300))
        self.assertEqual({r[0] for r in a},set(range(6)))
        self.assertTrue(all((r[1]!=0x42)==(r[0]==3) for r in a))
        self.assertEqual(a[-1],[1,0x42,0x96,20])

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_both_bus_rates_wire_data_mutations_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-i2c',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,I2C.CONFIGS,18,12)
            for name in I2C.CONFIGS:
                counts=read_json(out/f'{name}-boundaries/result.json')['counts']
                self.assertEqual(counts,dict(writes=7,reads=7,target_nacks=2,resets=1,stretches=12))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_each_demo_fault_fails_normal_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                with self.subTest(mutation=mutation):
                    out=Path(tmp)/f'm{mutation}'
                    p=run_example('local-i2c',out,'--configuration','half8','--iterations','2','--demo-bug',str(mutation))
                    self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                    self.assertFalse(read_json(out/'summary.json')['success'])
                    self.assertEqual(read_json(out/'half8-boundaries/result.json')['status'],'fail')


if __name__=='__main__':unittest.main()
