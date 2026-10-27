from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
AHB=load_example('local-ahb')


class AhbTest(unittest.TestCase):
    def test_pipeline_associates_data_with_previous_address(self):
        p=AHB.Plan(1);p.cycle(rst=0)
        p.pipeline([AHB.request(0,True,0x12345678),AHB.request(4,True,0xabcdef01),AHB.request(0),AHB.request(4)])
        reads=[r[10] for r in p.rows if r[11] and r[8] and not r[9] and not r[12]]
        self.assertEqual(reads,[0x12345678,0xabcdef01])
        self.assertEqual(p.rows[-1][-4:],[0x12345678,0xabcdef01,0,0])
        self.assertTrue(any(r[11] and r[8] and r[1] and r[2]>=2 for r in p.rows))

    def test_byte_and_halfword_use_addressed_data_lanes(self):
        p=AHB.Plan(0);p.cycle(rst=0)
        p.pipeline([AHB.request(0,True,0x11223344),AHB.request(1,True,0xaabbccdd,size=0),
                    AHB.request(2,True,0xa1b2c3d4,size=1),AHB.request(0)])
        self.assertEqual(p.rows[-1][-4:],[0xa1b2cc44,0,0,0])
        self.assertEqual(p.rows[-1][10],0xa1b2cc44)

    def test_error_has_two_response_cycles_and_cancels_next_address(self):
        for wait in (0,1,3):
            p=AHB.Plan(wait);p.cycle(rst=0);p.pipeline([AHB.request(32),AHB.request(0)])
            response=[r for r in p.rows if r[9]]
            self.assertEqual([r[8] for r in response],[0,1])
            self.assertEqual(response[-1][2],0)
            self.assertEqual(AHB.totals(p.rows)['accepted'],2)
            self.assertEqual(AHB.totals(p.rows)['errors'],1)

    def test_idle_busy_and_unselected_transfers_do_not_write(self):
        p=AHB.Plan(3);p.cycle(rst=0)
        p.pipeline([AHB.request(0,True,0xffffffff,trans=0),AHB.request(0,True,0xffffffff,trans=1),
                    AHB.request(0,True,0xffffffff,sel=0),AHB.request(0)])
        self.assertTrue(all(r[-4:]==[0,0,0,0] for r in p.rows))
        self.assertEqual(AHB.totals(p.rows)['writes'],0)

    def test_reset_aborts_data_phase_even_without_wait_states(self):
        p=AHB.Plan(0);p.cycle(rst=0);p.cycle(sel=1,trans=2,address=0,write=1)
        p.cycle(rst=0,data=0xffffffff);p.pipeline([AHB.request(0)])
        self.assertEqual(p.rows[-1][10],0)
        self.assertEqual(AHB.totals(p.rows)['writes'],0)

    def test_seed_reproducibility_and_waited_master_signal_holds(self):
        rows=AHB.random_vectors(17,100,3)
        self.assertEqual(rows,AHB.random_vectors(17,100,3))
        self.assertNotEqual(rows,AHB.random_vectors(18,100,3))
        for previous,current in zip(rows,rows[1:]):
            if previous[0] and current[0] and not previous[8] and not previous[9]:
                self.assertEqual(previous[1:8],current[1:8])

    def test_random_contains_bursts_busy_and_active_reset(self):
        rows=AHB.random_vectors(17,100,1)
        self.assertTrue(any(r[0] and r[2]==3 and r[6]==3 for r in rows))
        self.assertTrue(any(r[0] and r[2]==1 and r[6]==3 for r in rows))
        self.assertTrue(any(not b[0] and a[0] and a[1] and a[2]>=2 and a[8] for a,b in zip(rows,rows[1:])))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_all_wait_configurations_mutations_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-ahb',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,AHB.CONFIGS,21,18)
            for name in AHB.CONFIGS:
                c=read_json(out/f'{name}-boundaries/result.json')['counts']
                self.assertEqual(c['errors'],4)
                self.assertEqual(c['accepted'],c['reads']+c['writes']+c['errors']+1)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_each_demo_fault_fails_normal_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                with self.subTest(mutation=mutation):
                    out=Path(tmp)/f'm{mutation}'
                    p=run_example('local-ahb',out,'--configuration','wait1','--iterations','2','--demo-bug',str(mutation))
                    self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                    self.assertFalse(read_json(out/'summary.json')['success'])
                    self.assertEqual(read_json(out/'wait1-boundaries/result.json')['status'],'fail')


if __name__=='__main__':unittest.main()
