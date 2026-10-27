from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
AXI=load_example('local-axi4')


class Axi4Test(unittest.TestCase):
    def test_byte_strobes_preserve_existing_data(self):
        p=AXI.Plan();p.batch(n=1,m=1,seed=0x11223344)
        p.batch(n=1,m=1,seed=0xaabbccdd,mode=1)
        self.assertEqual(p.rows[-1][14],0x11bb33dd)
        p.batch(n=1,m=1,seed=0,mode=2)
        self.assertEqual(p.rows[-1][14],0x11bb33dd)

    def test_boundary_and_illegal_requests_do_not_modify_memory(self):
        self.assertFalse(AXI.invalid(0xff0,4,2,1))
        self.assertTrue(AXI.invalid(0xffc,2,2,1))
        p=AXI.Plan();p.batch();before=bytes(p.memory)
        p.batch(a=0xffc,b=3,n=2,size=2,seed=0xffffffff)
        self.assertEqual(bytes(p.memory),before)
        self.assertEqual(p.rows[-1][12:14],[1,1])
        self.assertEqual(p.rows[-1][14:],[0]*8)

    def test_reference_reads_after_both_writes_even_if_addresses_overlap(self):
        p=AXI.Plan();p.batch(a=0,b=0,n=1,m=1,seed=1)
        expected=1^0x5a5a5a5a
        self.assertEqual(p.rows[-1][14:16],[expected,expected])

    def test_seed_reproducibility_and_burst_bounds(self):
        rows=AXI.random_vectors(17,100)
        self.assertEqual(rows,AXI.random_vectors(17,100))
        self.assertNotEqual(rows,AXI.random_vectors(18,100))
        self.assertEqual({r[2] for r in rows},{1,2,3,4})
        self.assertTrue(all(len(r)==22 and r[12:14]==[0,0] for r in rows))
        self.assertEqual({r[4] for r in AXI.boundary_vectors()},{0,1,2,3})
        with self.assertRaises(ValueError):AXI.Plan().batch(n=5)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_two_outstanding_bursts_and_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-axi4',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,AXI.CONFIGS,26,6)
            result=read_json(out/'two-outstanding-boundaries/result.json')
            self.assertEqual(result['counts'],AXI.counts(AXI.boundary_vectors()))
            self.assertGreater(result['counts']['write_beats'],result['counts']['writes'])

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_demo_faults_cannot_pass_normal_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                with self.subTest(mutation=mutation):
                    out=Path(tmp)/str(mutation)
                    p=run_example('local-axi4',out,'--iterations','2','--demo-bug',str(mutation))
                    self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                    self.assertEqual(read_json(out/'two-outstanding-boundaries/result.json')['status'],'fail')
                    self.assertEqual(read_json(out/'coverage.json')['two-outstanding']['hit'],0)

if __name__=='__main__':unittest.main()
