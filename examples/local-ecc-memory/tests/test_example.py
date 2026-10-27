from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-ecc-memory')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-ecc-memory';GOALS=11
    def test_foreground_write_wins_scrub_of_old_data(self):
        p=P.Plan(4);p.cycle(rst=0);p.cycle(wr=1,addr=0,data=17);p.cycle(inject=1,ia=0,mask=1)
        p.cycle(wr=1,addr=0,data=99,scrub=1);p.cycle(rd=1,addr=0)
        self.assertEqual(p.rows[-1][9:12],[99,0,0])
    def test_double_error_is_reported_and_not_repaired(self):
        p=P.Plan(4);p.cycle(rst=0);p.cycle(wr=1,data=17);p.cycle(inject=1,mask=3)
        raw=p.mem[0];p.cycle(rd=1,scrub=1);self.assertEqual(p.mem[0],raw)
        self.assertEqual(p.rows[-1][10:12],[0,1]);p.cycle();self.assertEqual(p.rows[-1][-2:],[0,1])

if __name__=='__main__':unittest.main()
