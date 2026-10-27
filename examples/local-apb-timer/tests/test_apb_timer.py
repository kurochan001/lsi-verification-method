from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
APB=load_example('local-apb-timer')


class ApbTimerTest(unittest.TestCase):
    def test_deadline_pause_kick_and_load_priorities(self):
        counter=APB.Deadline()
        self.assertEqual(counter.step(False,load=2),0)
        self.assertEqual(counter.step(False,kick=True),0);self.assertEqual(counter.count,2)
        self.assertEqual(counter.step(True),0);self.assertEqual(counter.count,1)
        self.assertEqual(counter.step(True,kick=True),0);self.assertEqual(counter.count,2)
        self.assertEqual(counter.step(True,load=1,kick=True),0);self.assertEqual(counter.count,1)
        self.assertEqual(counter.step(True),1);self.assertEqual(counter.count,0)
        self.assertEqual(counter.step(True),0)

    def test_load_occurs_only_on_completed_command_and_truncates_reload(self):
        p=APB.Plan(4,2);p.cycle(rst=0);p.apb(4,0xfffffff5);p.apb(12,1)
        self.assertEqual(p.model.tr,5)
        self.assertEqual([r[9] for r in p.rows[-4:]],[0,0,0,5])
        self.assertEqual([r[6] for r in p.rows[-4:]],[0,0,0,1])

    def test_reset_aborts_request_and_requires_reprogramming(self):
        p=APB.Plan(4,2);p.apb(4,7);p.apb(12,1);p.apb(0,15,abort=True)
        self.assertEqual(p.model.control,0);self.assertEqual(p.model.tr,0)
        self.assertEqual(p.model.timer.count,0)
        self.assertFalse(any(r[6] for r in p.rows[-3:]))

    def test_boundary_plan_really_aligns_clear_kick_and_simultaneous_expiry(self):
        for wait in (0,2):
            rows=APB.boundary_vectors(4,wait)
            clear=kick=both=False
            for prior,row in zip(rows,rows[1:]):
                cmd=row[6] and row[3] and row[4]==12
                clear|=bool(cmd and row[5]&8 and row[14] and row[11])
                kick|=bool(cmd and row[5]&4 and not row[5]&2 and prior[10]==1 and row[13]==0)
                both|=bool(row[13] and row[14])
            self.assertTrue(clear);self.assertTrue(kick);self.assertTrue(both)

    def test_random_reproducibility_and_reset_ending(self):
        a=APB.random_vectors(17,40,4,2)
        self.assertEqual(a,APB.random_vectors(17,40,4,2))
        self.assertNotEqual(a,APB.random_vectors(18,40,4,2))
        self.assertEqual(a[-1][9:],[0,0,0,0,0,0,0,0,0])

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_all_rtl_widths_wait_states_mutations_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-apb-timer',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,APB.CONFIGS,24,24)
            for name in APB.CONFIGS:
                counts=read_json(out/f'{name}-boundaries/result.json')['counts']
                self.assertEqual(counts['errors'],3)
                self.assertEqual(counts['waits']==0,name.endswith('wait0'))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_each_demo_fault_fails_normal_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                with self.subTest(mutation=mutation):
                    out=Path(tmp)/f'm{mutation}'
                    p=run_example('local-apb-timer',out,'--configuration','width4-wait2','--iterations','2','--demo-bug',str(mutation))
                    self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                    self.assertFalse(read_json(out/'summary.json')['success'])
                    self.assertEqual(read_json(out/'width4-wait2-boundaries/result.json')['status'],'fail')


if __name__=='__main__':unittest.main()
