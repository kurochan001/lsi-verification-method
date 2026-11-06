import importlib.util
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('motion_io_test_cases',HERE/'cases.py');C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C);M=C.M
PARS=[dict(PERIOD=16,DEAD=2,FILTER=2),dict(PERIOD=24,DEAD=3,FILTER=3)]

class EncoderTests(unittest.TestCase):
    def test_full_forward_and_reverse_cycles_have_four_counts(self):
        q=M.Encoder()
        for raw in (1,3,2,0):
            for _ in range(6):q.step(1,raw)
        self.assertEqual(q.position,4)
        for raw in (2,3,1,0):
            for _ in range(6):q.step(1,raw)
        self.assertEqual((q.position,q.errors),(0,0))
    def test_short_glitches_do_not_count(self):
        for f in (2,3):
            q=M.Encoder(f)
            for raw in [0]*6+[1]*(f-1)+[0]*8:q.step(1,raw)
            self.assertEqual((q.position,q.errors),(0,0))
    def test_invalid_transition_is_reported_then_rebaselined(self):
        q=M.Encoder()
        for raw in [3]*6:q.step(1,raw)
        self.assertEqual((q.position,q.errors,q.previous),(0,1,3))
        for raw in [2]*6:q.step(1,raw)
        self.assertEqual((q.position,q.errors),(1,1))
    def test_signed_wraps_in_both_directions(self):
        for p in PARS:
            rows,e,n=C.make('wrap',p);self.assertEqual((n['wraps'],n['steps']),(2,2));self.assertEqual(M.signed(e[-1][11]),32767)
    def test_origin_and_reset_override_counts(self):
        q=M.Encoder();q.step(1,0,1,-123);self.assertEqual(q.position,-123);q.step(0,3,1,123);self.assertEqual(q.position,0)

    def test_origin_write_wins_over_a_count_on_the_same_edge(self):
        for p in PARS:
            c=C.Campaign(p);c.hold(p['FILTER']+3)
            for _ in range(p['FILTER']+2):c.tick(raw=1)
            c.tick(raw=1,origin_en=1,origin=500);self.assertEqual((c.q.position,c.q.step_flag),(500,0));self.assertEqual(c.q.previous,1)

class PwmTests(unittest.TestCase):
    def test_writes_wait_for_boundary_and_same_edge_write_wins(self):
        p=M.PWM();p.step(1,1,0,0,0);p.step(1,1,0,1,4);self.assertEqual((p.active,p.shadow),(8,4))
        while p.phase!=15:p.step(1,1,0,0,0)
        p.step(1,1,0,1,12);self.assertEqual((p.active,p.shadow,p.phase),(12,12,0))
    def test_invalid_duty_is_rejected(self):
        p=M.PWM();p.step(1,1,0,1,17);self.assertEqual((p.error,p.shadow),(1,8))
    def test_opposite_outputs_have_required_off_intervals(self):
        for pars in PARS:
            p=M.PWM(pars['PERIOD'],pars['DEAD']);old=0;off=100
            for _ in range(pars['PERIOD']*8):
                p.step(1,1,0,0,0);h,l=p.pins(1,1,0);self.assertFalse(h and l)
                if h or l:
                    current=1 if h else 2
                    if old and current!=old:self.assertGreaterEqual(off,pars['DEAD'])
                    old=current;off=0
                else:off+=1
    def test_stop_gates_both_outputs_without_waiting_for_step(self):
        p=M.PWM()
        for _ in range(5):p.step(1,1,0,0,0)
        self.assertEqual(p.pins(1,1,1),[0,0])
    def test_seeded_campaigns_and_complete_column_widths(self):
        for p in PARS:
            for name in (*C.NAMES,'random'):
                rows,e,n=C.make(name,p);self.assertEqual(n['rows'],len(rows));self.assertEqual(len(rows),len(e));self.assertTrue(all(len(r)==8 for r in rows));self.assertTrue(all(len(r)==22 for r in e));self.assertTrue(all(0<=v<2**32 for row in rows+e for v in row))
            self.assertEqual(C.make('random',p,17),C.make('random',p,17));self.assertNotEqual(C.make('random',p,17)[0],C.make('random',p,18)[0])
    def test_stimulus_rejects_values_that_would_be_truncated(self):
        c=C.Campaign(PARS[0])
        for fields in (dict(enable=2),dict(origin=32768),dict(raw=4),dict(duty=2**32)):
            with self.assertRaises(ValueError):c.tick(**fields)
if __name__=='__main__':unittest.main()
