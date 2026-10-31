from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-riscv-pmp')


class PmpTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-riscv-pmp';GOALS=16

    def test_priority_and_partial_access_override_machine_bypass(self):
        p=P.Plan(16);p.cycle(rst=0)
        p.entry(0,2,0x100,1);p.entry(1,3,0,7,length=512)
        self.assertEqual(p.check(0x100,2,1,0),(0,0))
        self.assertEqual(p.check(0xfe,2,0,1),(0,0)) # starts outside the first matching entry
        self.assertEqual(p.check(0x100,2,1,1),(1,0))
        self.assertEqual(p.check(0x104,2,1,0),(1,1))
        for addr in (0xfe,0x100,0x104):
            for machine in (0,1):p.cycle(address=addr,size=2,kind=1,machine=machine)
        result=simulate_vectors(P,p.rows)
        self.assertEqual(result.returncode,0,result.stdout)

    def test_tor_predecessor_and_off_lock_until_reset(self):
        p=P.Plan(16);p.cycle(rst=0);p.entry(0,0,0x100,0,True)
        p.cycle(pa=1,index=0,data=1);self.assertEqual(p.pa[0],64)
        p.entry(2,1,0x300,1,True)
        p.cycle(pa=1,index=1,data=123);self.assertEqual(p.pa[1],0)
        p.cycle(rst=0);p.cycle(pa=1,index=1,data=123);self.assertEqual(p.pa[1],123)
        p.cycle();result=simulate_vectors(P,p.rows)
        self.assertEqual(result.returncode,0,result.stdout)

    def test_napot_extremes_and_reversed_tor(self):
        p=P.Plan(16)
        for length in (8,16,32,256,65536,131072):
            p.cycle(rst=0);p.entry(0,3,0,7,length=length)
            self.assertEqual(p.region(0),range(length))
            self.assertEqual(p.check(65535,2,0,1)[0],0) # PA overflow, even under all-space entry
            p.cycle(address=65535,size=2,machine=1);p.cycle(address=65532,size=2)
        p.cycle(rst=0);p.entry(0,0,0x200);p.entry(1,1,0x100)
        self.assertEqual(list(p.region(1)),[])
        p.cycle(address=0x180)
        p.cycle(address=0,size=3,machine=1);p.cycle(address=0,kind=3,machine=1)
        self.assertEqual([r[9] for r in p.rows[-2:]],[0,0])
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_checker_rejects_incorrect_permission_oracle(self):
        p=P.Plan(16);p.cycle(rst=0);p.cycle(machine=0)
        p.rows[-1][9]=1
        result=simulate_vectors(P,p.rows)
        self.assertNotEqual(result.returncode,0);self.assertIn('CHECK_FAIL PMP_DECISION',result.stdout)


if __name__=='__main__':unittest.main()
