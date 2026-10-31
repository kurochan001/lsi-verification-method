from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-sv32')


class Sv32Tests(SystemContract,unittest.TestCase):
    EXAMPLE='local-sv32';GOALS=17

    def test_physical_high_bits_and_superpage_offset(self):
        va=0x81234567;root=0x3fffff;ptr=(0x2fffff<<10)|1
        memory=P.page_table(va,root,ptr,(0x3abcde<<10)|0xdf)
        reads,pa,fault=P.translate(va,root,0,1,0,0,memory)
        self.assertEqual(pa,0x3abcde567);self.assertEqual(fault,0)
        self.assertEqual(reads[0][0],0x3fffff810);self.assertEqual(reads[1][0],0x2fffff8d0)
        p=P.Plan(2);p.cycle(rst=0);p.transfer(memory=memory)
        p.transfer(memory=P.page_table(va,root,(0x300000<<10)|0xdf))
        self.assertEqual(p.result,(0x300234567,0))
        result=simulate_vectors(P,p.rows,{'WAIT_CYCLES':2});self.assertEqual(result.returncode,0,result.stdout)

    def test_supervisor_sum_never_allows_user_page_execution(self):
        p=P.Plan(0);p.cycle(rst=0);va=0x81234567;root=0x3fffff;ptr=0x100001
        for user in (0,1):
            for sum_enable in (0,1):
                for kind in (0,1,2):
                    memory=P.page_table(va,root,ptr,(0x1234<<10)|0xdf)
                    expected=0 if user or (sum_enable and kind!=2) else 1
                    self.assertEqual(P.translate(va,root,kind,user,sum_enable,0,memory)[2],expected)
                    p.transfer(kind=kind,user=user,sum_enable=sum_enable,memory=memory)
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_pte_access_fault_distinct_from_page_fault_at_both_levels(self):
        va=0x81234567;root=0x3fffff;ptr=0x100001;p=P.Plan(0);p.cycle(rst=0)
        memory=P.page_table(va,root,ptr,0);second=(ptr>>10)*4096+((va>>12)&1023)*4
        memory[second]=None;p.transfer(memory=memory);self.assertEqual(p.result,(0,2))
        memory[second]=1;p.transfer(memory=memory);self.assertEqual(p.result,(0,1))
        memory[next(iter(memory))]=None;p.transfer(memory=memory);self.assertEqual(p.result,(0,2))
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_checker_rejects_wrong_pte_fetch_address(self):
        p=P.Plan(0);p.cycle(rst=0);p.transfer(memory={})
        row=next(r for r in p.rows if r[14]);row[15]^=4
        result=simulate_vectors(P,p.rows);self.assertNotEqual(result.returncode,0)
        self.assertIn('CHECK_FAIL VM_PTE_ADDRESS',result.stdout)


if __name__=='__main__':unittest.main()
