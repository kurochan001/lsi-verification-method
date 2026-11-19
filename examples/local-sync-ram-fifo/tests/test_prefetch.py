"""Real clock configurations, replay and strict process failure classification."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
HERE=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('prefetch_test',HERE/'run.py')
R=importlib.util.module_from_spec(s);s.loader.exec_module(R)


class PrefetchTests(unittest.TestCase):
    def args(self,**values):
        return SimpleNamespace(**dict(dict(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),**values))

    def test_every_width_clock_latency_and_mutation_on_real_rtl(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,self.args(),tmp)
            for case in R.cases(SimpleNamespace(seed=17,profile='smoke')):
                result=sim.execute(case)
                self.assertEqual(result['status'],'detected' if case.get('expected_failure') else 'pass',result)
                if not case.get('expected_failure'):self.assertTrue(R.GOALS<=set(result['goals']))

    def test_same_seed_replays_accepted_traffic_and_stalls(self):
        base=R.cases(SimpleNamespace(seed=17,profile='smoke'))[0]
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,self.args(),tmp)
            for name,seed in (('first',17),('again',17),('different',18)):
                result=sim.execute(dict(base,id=name,seed=seed));self.assertEqual(result['status'],'pass',result)
            def read(name):return (Path(tmp)/name/'trace.csv').read_bytes()
            self.assertEqual(read('first'),read('again'))
            self.assertNotEqual(read('first'),read('different'))

    def test_build_error_is_not_mutation_detection(self):
        case=R.cases(SimpleNamespace(seed=17,profile='smoke'))[-1]
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,self.args(iverilog=str(Path(tmp)/'absent')),tmp)
            self.assertNotEqual(sim.execute(case)['status'],'detected')

    def test_unrelated_simulator_exit_is_not_mutation_detection(self):
        case=R.cases(SimpleNamespace(seed=17,profile='smoke'))[-1]
        with tempfile.TemporaryDirectory() as tmp:
            tool=Path(tmp)/'crash';tool.write_text('#!/bin/sh\nexit 3\n');tool.chmod(0o755)
            sim=R.S.Simulator(R,self.args(vvp=str(tool)),tmp)
            self.assertNotEqual(sim.execute(case)['status'],'detected')


if __name__=='__main__':unittest.main()
