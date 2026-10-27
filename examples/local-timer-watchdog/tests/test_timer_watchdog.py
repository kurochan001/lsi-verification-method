from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
TIMER=load_example('local-timer-watchdog')


class TimerTest(unittest.TestCase):
    def test_irq_event_wins_and_one_shot_does_not_repeat(self):
        rows=TIMER.reference([TIMER.stimulus(rst_n=0),TIMER.stimulus(timer_load=1,timer_reload=1),
            TIMER.stimulus(timer_enable=1,clear_irq=1),TIMER.stimulus(timer_enable=1,clear_irq=1),
            TIMER.stimulus(timer_enable=1)])
        self.assertEqual(rows[2][10:],[0,0,1,0,1])
        self.assertEqual(rows[3][10:],[0,0,0,0,0])
        self.assertEqual(rows[4][10:],[0,0,0,0,0])

    def test_watchdog_kick_load_disable_and_rearm_priorities(self):
        rows=TIMER.reference([TIMER.stimulus(watchdog_load=1,watchdog_reload=1),
            TIMER.stimulus(watchdog_enable=1,kick=1),TIMER.stimulus(watchdog_enable=1),
            TIMER.stimulus(watchdog_enable=1,kick=1),TIMER.stimulus(kick=1),
            TIMER.stimulus(watchdog_enable=1,kick=1,watchdog_load=1,watchdog_reload=2)])
        self.assertEqual([(r[11],r[13]) for r in rows],[(1,0),(1,0),(0,1),(1,0),(1,0),(2,0)])

    def test_periodic_one_and_pause_use_enabled_clocks(self):
        rows=TIMER.reference([TIMER.stimulus(timer_load=1,timer_reload=1),
            *[TIMER.stimulus(timer_enable=1,periodic=1) for _ in range(3)],
            TIMER.stimulus(periodic=1),TIMER.stimulus(timer_enable=1,periodic=1)])
        self.assertEqual([r[14] for r in rows],[0,1,1,1,0,1])
        self.assertTrue(all(r[10]==1 for r in rows))

    def test_reset_clears_both_pending_state_and_events(self):
        rows=TIMER.reference([TIMER.stimulus(timer_load=1,timer_reload=1,watchdog_load=1,watchdog_reload=1),
            TIMER.stimulus(timer_enable=1,watchdog_enable=1),TIMER.stimulus(rst_n=0,kick=1,clear_irq=1)])
        self.assertEqual(rows[1][10:],[0,0,1,1,1])
        self.assertEqual(rows[2][10:],[0,0,0,0,0])

    def test_random_reproducibility_and_width_limits(self):
        for width in (4,8):
            a=TIMER.random_inputs(17,200,width)
            self.assertEqual(a,TIMER.random_inputs(17,200,width))
            self.assertNotEqual(a,TIMER.random_inputs(18,200,width))
            self.assertTrue(all(0<=r[4]<1<<width and 0<=r[7]<1<<width for r in a))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_rtl_both_widths_mutations_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-timer-watchdog',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,TIMER.CONFIGS,20,12)
            for name in TIMER.CONFIGS:
                counts=read_json(out/f'{name}-boundaries/result.json')['counts']
                self.assertGreater(counts['timer_expiries'],8)
                self.assertGreater(counts['watchdog_resets'],3)


if __name__=='__main__':unittest.main()
