from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-tlb')


class TlbTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-tlb';GOALS=21

    def test_superpage_fence_inside_mapping_removes_old_translation(self):
        p=P.Plan(2);m={};va=0x80401000;P.mapping(m,va,0,0x300000,large=True);p.cycle(rst=0)
        p.transfer(m,va=va);p.fence(av=1,sv=1,va=va+0x123000,asid=0)
        P.mapping(m,va,0,0x310000,large=True);begin=len(p.rows);p.transfer(m,va=va+0x201234)
        self.assertEqual(p.result,(0x310202234,0));self.assertEqual(p.rows[begin][20],0)
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_asid_fence_preserves_global_translation_from_parent_pte(self):
        p=P.Plan(4);m={};va=0x60001020
        for asid in (0,1,5):P.mapping(m,va,asid,0x33000,global_parent=True)
        p.cycle(rst=0);p.transfer(m,va=va);p.fence(sv=1,asid=0)
        begin=len(p.rows);p.transfer(m,va=va+7,asid=5)
        self.assertEqual(p.rows[begin][20],1);self.assertEqual(p.result,(0x33000027,0))
        p.fence(av=1,va=va);begin=len(p.rows);p.transfer(m,va=va,asid=1)
        self.assertEqual(p.rows[begin][20],0)
        for asid,ppn in ((1,0x10001),(0x101,0x10101)):
            P.mapping(m,0x40001020,asid,ppn);p.transfer(m,asid=asid)
            self.assertEqual(p.result,(ppn*4096+0x20,0))
        result=simulate_vectors(P,p.rows,{'ENTRIES':4});self.assertEqual(result.returncode,0,result.stdout)

    def test_cached_permissions_are_rechecked_for_each_access(self):
        p=P.Plan(2);m={};va=0x70001020;P.mapping(m,va,0,0x44000,flags=0x5f);p.cycle(rst=0)
        p.transfer(m,va=va);p.transfer(m,va=va,kind=1)
        self.assertEqual(p.result,(0,1))
        p.transfer(m,va=va,kind=2,user=0,sum_enable=1);self.assertEqual(p.result,(0,1))
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_fence_waits_for_walk_and_response_before_invalidation(self):
        p=P.Plan(2);m={};va=0x40001020;P.mapping(m,va,0,0x10000);p.cycle(rst=0)
        q=dict(va=va,root=1,asid=0,kind=0,user=1,sum_enable=0,mxr=0,bare=0,memory=m);f=(1,0,va,0)
        p.cycle(request=q)
        while not p.valid:self.assertEqual(p.cycle(fence=f)[1],0)
        self.assertEqual(p.cycle(fence=f,ready=0)[1],0);p.cycle(fence=f)
        self.assertEqual(p.cycle(request=q,fence=f),(0,1))
        begin=len(p.rows);p.transfer(m);self.assertEqual(p.rows[begin][20],0)
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)


if __name__=='__main__':unittest.main()
