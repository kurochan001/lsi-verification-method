import importlib.util
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ecu_cases_test',HERE/'cases.py');C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C)
PARS=[dict(DATA_ID=0xa12f,WINDOW_MIN=3,WINDOW_MAX=9,FRESH_MAX=13),dict(DATA_ID=0x35c9,WINDOW_MIN=5,WINDOW_MAX=13,FRESH_MAX=19)]
class EcuTests(unittest.TestCase):
    def test_early_minimum_and_maximum_service_edges(self):
        for p in PARS:
            for distance,wanted in ((p['WINDOW_MIN']-1,2),(p['WINDOW_MIN'],0),(p['WINDOW_MAX'],0)):
                c=C.Campaign(p);c.start()
                for _ in range(distance-1):c.tick()
                c.tick(service=1);self.assertEqual(c.m.cause,wanted)
            c=C.Campaign(p);c.start()
            for _ in range(p['WINDOW_MAX']-1):c.tick();self.assertEqual(c.m.cause,0)
            c.tick();self.assertEqual(c.m.cause,4)
    def test_corrupt_frames_cannot_keep_commands_fresh(self):
        for p in PARS:
            _,out,n=C.make('freshness-errors',p);self.assertTrue(any(r[4]==8 for r in out));self.assertGreater(n['rejected'],0);self.assertEqual({r[10] for r in out if r[9]},{1,2,3})
    def test_fault_cancels_pending_instead_of_applying(self):
        for p in PARS:
            c=C.Campaign(p);c.start();c.send(payload=700);e=c.tick(external=1)
            self.assertEqual(e[1:8],[0,1,0,1,1,0,1]);self.assertEqual(c.counts['validated'],1);self.assertEqual(c.counts['cancelled'],1);self.assertEqual(c.counts['applied'],0)
    def test_external_fault_latches_while_off_and_beats_arm(self):
        c=C.Campaign(PARS[0]);c.tick(rst=0);e=c.tick(external=1);self.assertEqual((e[1],e[2],e[4],e[5]),(0,1,1,1))
        e=c.tick(recover=1,permit=1);self.assertEqual((e[2],e[4]),(0,0))
        e=c.tick(arm=1,external=1);self.assertEqual((e[1],e[2],e[4]),(0,1,1))
    def test_ack_does_not_clear_latched_fault(self):
        c=C.Campaign(PARS[0]);c.start();c.tick(external=1);e=c.tick(ack=1)
        self.assertEqual((e[1],e[2],e[4],e[5]),(0,1,1,0))
    def test_recovery_needs_permission_and_a_separate_arm(self):
        c=C.Campaign(PARS[0]);c.start();c.tick(external=1)
        self.assertEqual(c.tick(recover=1,permit=1,external=1)[2],1)
        self.assertEqual(c.tick(recover=1,arm=1)[2],1)
        e=c.tick(recover=1,permit=1,arm=1);self.assertEqual((e[1],e[2],e[3],e[4]),(0,0,0,0))
        self.assertEqual(c.tick(arm=1)[1],1);self.assertEqual(c.m.guard.expected,0)
    def test_simultaneous_late_and_range_fault_overrides_disarm(self):
        for p in PARS:
            c=C.Campaign(p);c.start()
            for _ in range(p['WINDOW_MAX']-2):c.tick()
            c.send(payload=1001);e=c.tick(disarm=1,ack=1)
            self.assertEqual((e[1],e[2],e[3],e[4],e[5],e[6],e[7]),(0,1,0,20,1,0,1))
    def test_command_commit_rescues_the_exact_freshness_deadline(self):
        for p in PARS:
            c=C.Campaign(p);c.start();c.advance(p['FRESH_MAX']-2,refresh=False)
            c.send(payload=1000,service=int(c.m.time+1-c.m.last_service==p['WINDOW_MIN']))
            self.assertEqual(c.m.time-c.m.last_apply,p['FRESH_MAX']-1)
            e=c.tick(service=int(c.m.time+1-c.m.last_service==p['WINDOW_MIN']));self.assertEqual((e[1],e[3],e[4],e[6]),(1,1000,0,1))
    def test_all_campaigns_finish_with_exact_queue_accounting(self):
        for p in PARS:
            for name in C.NAMES:
                rows,e,n=C.make(name,p);self.assertEqual(len(rows),len(e));self.assertEqual(n['inputs'],n['validated']+n['rejected']);self.assertEqual(n['validated'],n['applied']+n['cancelled']+n['reset_cancels']);self.assertEqual(e[-1][1:4],[0,0,0]);self.assertEqual(e[-1][-1],0)
    def test_reset_pending_is_counted_separately(self):
        _,_,n=C.make('recovery-reset',PARS[0]);self.assertEqual(n['reset_cancels'],1)
    def test_reproducible_random_episodes(self):
        self.assertEqual(C.make('random',PARS[0],17),C.make('random',PARS[0],17));self.assertNotEqual(C.make('random',PARS[0],17)[0],C.make('random',PARS[0],18)[0])
    def test_input_and_timing_ranges(self):
        c=C.Campaign(PARS[0])
        for kwargs in (dict(service=2),dict(frame=1<<48),dict(extra=1)):
            with self.assertRaises(ValueError):c.tick(**kwargs)
        with self.assertRaises(ValueError):C.M.ECU(dict(DATA_ID=0,WINDOW_MIN=3,WINDOW_MAX=3,FRESH_MAX=5))
if __name__=='__main__':unittest.main()
