"""Anchor cross-word byte mapping, partial commit and real adapter detection."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
HERE=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('split_test',HERE/'run.py')
R=importlib.util.module_from_spec(s);s.loader.exec_module(R)


class SplitTests(unittest.TestCase):
    def test_known_cross_word_bytes_in_both_endians(self):
        for big,expected in ((False,[0x44,0x33,0x22,0x11]),(True,[0x11,0x22,0x33,0x44])):
            p=R.M.Plan(big=big);p.memory=[0]*len(p.memory)
            p.step(1,3,4,0x11223344)
            self.assertEqual(p.memory[3:7],expected)
            self.assertEqual(p.rows[-1][7],2)
            p.step(2,3,4);self.assertEqual(p.rows[-1][5],0x11223344)

    def test_second_word_error_reset_and_range_keep_defined_bytes(self):
        p=R.M.Plan();p.memory=[0x99]*len(p.memory)
        p.step(1,3,4,0x11223344,1)
        self.assertEqual(p.memory[3:7],[0x44,0x99,0x99,0x99])
        self.assertEqual(p.rows[-1][6:8],[1,1])
        p.step(3,7,4,0xaabbccdd)
        self.assertEqual(p.memory[7:11],[0xdd,0x99,0x99,0x99])
        before=p.memory[:];p.step(1,63,2,0);p.step(0)
        self.assertEqual(p.memory,before)

    def test_all_real_widths_endians_and_mutations(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),tmp)
            for case in R.cases(SimpleNamespace(seed=17,profile='smoke')):
                result=sim.execute(case)
                self.assertEqual(result['status'],'detected' if case.get('expected_failure') else 'pass',result)
                if not case.get('expected_failure'):self.assertTrue(R.GOALS<=set(result['goals']))

    def test_replay_and_corrupt_reference_cannot_pass(self):
        self.assertEqual(R.M.stimulus(seed=17),R.M.stimulus(seed=17))
        self.assertNotEqual(R.M.stimulus(seed=17),R.M.stimulus(seed=18))
        case=R.cases(SimpleNamespace(seed=17,profile='smoke'))[0]
        lines=case['text'].splitlines();index=next(i for i,line in enumerate(lines) if line.split()[0]=='2')
        fields=lines[index].split();fields[5]=format(int(fields[5],16)^1,'x');lines[index]=' '.join(fields)
        case=dict(case,id='wrong-reference',text='\n'.join(lines)+'\n',expected_failure=R.LABEL)
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),tmp)
            self.assertEqual(sim.execute(case)['status'],'detected')


if __name__=='__main__':unittest.main()
