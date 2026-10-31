from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-dram')

class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-dram';GOALS=18
    def check_rtl(self,rows,parameters=None):
        r=simulate_vectors(P,rows,parameters=parameters)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_every_cell_read_after_write_uses_independent_native_memory(self):
        p=P.Plan(P.CONFIGS['fast']);p.cycle(rst=0)
        for b in range(2):
            for r in range(4):
                for c in range(4):p.access(1,b,r,c,0xabcdef00+b*16+r*4+c)
        for b in range(2):
            for r in range(4):
                for c in range(4):self.assertEqual(p.access(0,b,r,c),0xabcdef00+b*16+r*4+c)
        self.check_rtl(p.rows,P.CONFIGS['fast'])
        r=simulate_vectors(P,p.rows,parameters=P.CONFIGS['fast'],replacements={'dram_controller.sv':[('resp_data<=read_data;','resp_data<=read_data^32\'d1;')]})
        self.assertNotEqual(r.returncode,0);self.assertIn('CHECK_FAIL DRAM_DATA',r.stdout)

    def test_refresh_progress_is_independent_of_response_ready(self):
        for params in P.CONFIGS.values():
            p=P.Plan(params);p.cycle(rst=0);p.access(1,0,0,0,0x12345678)
            start=len(p.rows);p.access(0,0,0,0,hold=params['TREFI']*4)
            held=[r for r in p.rows[start:] if r[9] and not r[7]]
            self.assertGreaterEqual(sum(r[11]==5 for r in held),2)
            self.assertTrue(all(r[10]==0x12345678 for r in held));self.check_rtl(p.rows,params)

    def test_write_recovery_prevents_early_conflicting_row_precharge(self):
        for params in P.CONFIGS.values():
            p=P.Plan(params);p.cycle(rst=0);p.access(1,0,0,0,1);p.access(0,0,1,0)
            write=next(i for i,r in enumerate(p.rows) if r[11]==3)
            pre=next(i for i,r in enumerate(p.rows) if i>write and r[11]==4)
            self.assertGreaterEqual(pre-write,params['TWR']);self.check_rtl(p.rows,params)

    def test_fixture_reset_cancels_request_and_clears_memory(self):
        p=P.Plan(P.CONFIGS['fast']);p.cycle(rst=0);p.access(1,0,0,0,0xa5)
        while not p.cycle(req=(0,0,0,0,0)):pass
        p.cycle(rst=0);self.assertEqual(p.access(0,0,0,0),0);self.check_rtl(p.rows,P.CONFIGS['fast'])

if __name__=='__main__':unittest.main()
