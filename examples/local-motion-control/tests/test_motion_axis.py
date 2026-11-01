import importlib.util
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('axis_test_cases',HERE/'cases.py');C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C);M=C.M
PARS=[dict(PERIOD=16,DEAD=2,FILTER=2,SAMPLE=64,LATENCY=3,SPEED_LIMIT=6),dict(PERIOD=24,DEAD=3,FILTER=3,SAMPLE=96,LATENCY=5,SPEED_LIMIT=8)]

def calculate(pi,error):
    pi.step(1,0,1,0,error)
    for _ in range(pi.latency):pi.step(1,0,0,0,0)
    return pi.effort

class PiTests(unittest.TestCase):
    def test_rounding_ties_are_symmetric(self):
        p=M.PI(8,3);p.integral=-1;self.assertEqual(calculate(p,1),1)
        p=M.PI(8,3);p.integral=1;self.assertEqual(calculate(p,-1),-1)
    def test_antiwindup_prevents_accumulation_and_release_is_neutral(self):
        for sign in (-1,1):
            p=M.PI(8,3)
            for _ in range(20):self.assertEqual(calculate(p,sign*100),sign*8);self.assertEqual((p.integral,p.anti),(0,1))
            self.assertEqual(calculate(p,0),0)
    def test_integrator_and_output_bounds(self):
        p=M.PI(12,5)
        for error in [0,1,-1,32767,-32768,65535,-65535]*8:
            calculate(p,error);self.assertLessEqual(abs(p.effort),12);self.assertLessEqual(abs(p.integral),192)
    def test_hold_and_clear_do_not_produce_late_completion(self):
        p=M.PI(8,3);p.step(1,0,1,0,12)
        for _ in range(20):p.step(1,0,0,1,0);self.assertEqual((p.busy,p.done),(1,0))
        p.step(1,1,0,0,0)
        for _ in range(5):p.step(1,0,0,0,0);self.assertEqual((p.busy,p.done,p.effort),(0,0,0))

class LoopTests(unittest.TestCase):
    def test_all_fixed_campaigns_drain_and_preserve_job_accounting(self):
        for p in PARS:
            for name in C.NAMES:
                rows,e,n=C.make(name,p);self.assertEqual(n['rows'],len(rows));self.assertEqual(len(rows),len(e));self.assertEqual(n['samples'],n['updates']+n['cancels']+n['reset_cancels']);self.assertTrue(all(len(r)==45 for r in e));self.assertTrue(all(0<=v<2**32 for row in rows+e for v in row))
    def test_tracking_reversal_and_load_have_explicit_settling_windows(self):
        for p in PARS:
            for name in ('tracking','reversal','load-step','saturation'):
                rows,e,n=C.make(name,p);checked=[(r,o) for r,o in zip(rows,e) if r[13]];self.assertTrue(checked)
                for r,o in checked:self.assertEqual((o[0],o[1]),(1,0));self.assertLessEqual(abs(M.S(o[6])-M.S(r[5])),2)
    def test_each_fault_source_is_observed(self):
        for p in PARS:
            for name,bit in (('estop-rearm',1),('encoder-invalid',2),('deadline',4),('encoder-stuck',8),('mechanical-stall',8),('overspeed',16),('position-wrap',32)):
                rows,e,n=C.make(name,p);self.assertTrue(any(o[1]&bit for o in e),(p,name))
    def test_ack_does_not_arm_and_rearm_is_neutral(self):
        rows,e,n=C.make('estop-rearm',PARS[0]);self.assertTrue(any(r[3] and o[1]!=0 and not o[0] for r,o in zip(rows,e)))
        last=0;neutral=False
        for r,o in zip(rows,e):
            if o[0] and not last:neutral=True
            if o[3]:neutral=False
            if neutral and o[28]:self.assertEqual(o[23],8)
            last=o[0]
    def test_deadline_boundary_completes_without_fault(self):
        for p in PARS:
            rows,e,n=C.make('deadline-boundary',p);self.assertTrue(all(o[1]==0 for o in e));self.assertGreater(n['updates'],0)
    def test_reset_cancels_pending_job(self):
        rows,e,n=C.make('reset-pending',PARS[0]);self.assertEqual((n['resets'],n['reset_cancels']),(1,1));self.assertTrue(all(o[1]==0 for o in e))
    def test_sensor_freeze_is_distinct_from_a_frozen_plant(self):
        _,a,_=C.make('encoder-stuck',PARS[0]);_,b,_=C.make('mechanical-stall',PARS[0]);self.assertGreater(max(M.S(o[39]) for o in a),0);self.assertTrue(all(o[39]==0 for o in b))
    def test_invalid_signed_inputs_are_not_truncated(self):
        c=C.Campaign(PARS[0])
        for values in (dict(target=2**32+1),dict(target=32768),dict(origin=-32769),dict(load=1025),dict(mode=3),dict(arm=2)):
            with self.assertRaises(ValueError):c.tick(**values)
    def test_origin_and_arm_share_the_new_velocity_baseline(self):
        for p in PARS:
            rows,e,n=C.make('origin-arm',p);self.assertTrue(all(o[1]==0 for o in e));self.assertEqual(M.S(e[-1][6]),1000);self.assertGreater(n['updates'],0)
    def test_random_campaigns_are_reproducible_and_settle(self):
        self.assertEqual(C.make('random',PARS[0],17,1),C.make('random',PARS[0],17,1));self.assertNotEqual(C.make('random',PARS[0],17,1)[0],C.make('random',PARS[0],18,1)[0])
if __name__=='__main__':unittest.main()
