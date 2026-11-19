"""Byte-oracle anchors, real RTL mutations and unknown stored-data rejection."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

HERE=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('ecc_rmw_test',HERE/'run.py')
R=importlib.util.module_from_spec(s);s.loader.exec_module(R)


class RmwTests(unittest.TestCase):
    def test_known_byte_merge_and_faulted_partial_write(self):
        for width in (32,64):
            p=R.M.Plan(width,8,17);full=(1<<p.size)-1
            p.step(1,0,0x11223344,full);p.step(3,0,fault=1)
            p.step(1,0,0xaa00,2);self.assertEqual(p.rows[-1][6:9],[1,0,0])
            p.step(2,0);self.assertEqual(p.rows[-1][5],0x1122aa44)
            p.step(3,0,fault=3);before=p.bytes[:]
            p.step(1,0,0xff,1);self.assertEqual(p.bytes,before)
            self.assertEqual(p.rows[-1][6:9],[0,1,1])

    def test_zero_mask_scrub_and_reset_contract(self):
        p=R.M.Plan(32,8,17);p.step(1,0,0x12345678,15);p.step(3,0,fault=2)
        p.step(1,0,0,0);self.assertEqual(p.faults[0],2)
        p.step(0);self.assertEqual(p.faults[0],2)
        p.step(4);self.assertEqual(p.faults[0],0)
        p.step(2,0);self.assertEqual(p.rows[-1][5],0x12345678)

    def test_seed_replay_and_real_rtl_both_widths(self):
        self.assertEqual(R.M.stimulus(seed=17),R.M.stimulus(seed=17))
        self.assertNotEqual(R.M.stimulus(seed=17),R.M.stimulus(seed=18))
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),tmp)
            for case in R.cases(SimpleNamespace(seed=17,profile='smoke'))[:2]:
                result=sim.execute(case);self.assertEqual(result['status'],'pass',result)
                self.assertTrue(R.GOALS<=set(result['goals']))

    def test_every_mutation_is_detected_by_real_rtl(self):
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),tmp)
            for case in R.cases(SimpleNamespace(seed=17,profile='smoke'))[2:]:
                self.assertEqual(sim.execute(case)['status'],'detected',case)

    def test_unknown_physical_storage_cannot_pass_four_state_comparison(self):
        case=R.cases(SimpleNamespace(seed=17,profile='smoke'))[0]
        lines=case['text'].splitlines()
        first=next(i for i,line in enumerate(lines) if line.split()[0]=='3')
        values=lines[first].split();values[4]='x';lines[first]=' '.join(values)
        case=dict(case,id='unknown-storage',text='\n'.join(lines)+'\n',expected_failure=R.LABEL)
        with tempfile.TemporaryDirectory() as tmp:
            sim=R.S.Simulator(R,SimpleNamespace(iverilog='iverilog',vvp='vvp',timeout=30,waves=False),tmp)
            self.assertEqual(sim.execute(case)['status'],'detected')


if __name__=='__main__':unittest.main()
