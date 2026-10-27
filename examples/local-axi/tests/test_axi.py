from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
AXI=load_example('local-axi')


class AxiTest(unittest.TestCase):
    def test_write_data_before_address_is_buffered(self):
        p=AXI.Plan(2);p.cycle(rst=0)
        p.cycle(wv=1,wd=0x11223344,ws=15);p.cycle(wd=0xffffffff)
        self.assertIsNone(p.model.b)
        p.cycle(awv=1,awa=4,wd=0xffffffff);p.idle(3)
        self.assertEqual(p.model.read_word(4),(0x11223344,0))
        self.assertEqual(p.model.b,0)

    def test_partial_and_zero_strobes_preserve_other_bytes(self):
        p=AXI.Plan(0);p.cycle(rst=0)
        p.write(0,0x11223344);p.write(0,0xaabbccdd,strobe=5);p.write(0,0,strobe=0)
        self.assertEqual(p.model.read_word(0),(0x11bb33dd,0))

    def test_same_edge_read_snapshots_before_write_commit(self):
        for delay in (0,2):
            p=AXI.Plan(delay);p.cycle(rst=0)
            p.cycle(awv=1,awa=0,wv=1,wd=0x11223344,ws=15);p.idle(delay)
            collision=p.cycle(arv=1,ara=0);p.idle(delay+1)
            self.assertEqual(collision[-4:],[0x11223344,0,0,0])
            self.assertEqual(p.model.r,(0,0))
            self.assertEqual(p.model.read_word(0),(0x11223344,0))
            p.cycle(br=1,rr=1)

    def test_reset_discards_half_requests_and_pending_responses(self):
        for first in ('aw','w','pair','read'):
            p=AXI.Plan(0);p.cycle(rst=0)
            if first=='aw':p.cycle(awv=1,awa=0)
            elif first=='w':p.cycle(wv=1,wd=0xffffffff,ws=15)
            elif first=='pair':p.cycle(awv=1,awa=0,wv=1,wd=0xffffffff,ws=15);p.idle(2)
            else:p.cycle(arv=1,ara=0);p.idle(2)
            p.cycle(rst=0);p.idle(3)
            self.assertEqual(p.model.outputs(),[1,1,1,0,0,0,0,0])
            self.assertEqual(p.model.read_word(0),(0,0))

    def test_response_generation_does_not_wait_for_ready(self):
        first_valid=[]
        for ready in (0,1):
            p=AXI.Plan(2);p.cycle(rst=0)
            p.cycle(awv=1,awa=0,wv=1,wd=1,ws=15,arv=1,ara=4,br=ready,rr=ready)
            p.idle(6,br=ready,rr=ready)
            first_valid.append((next(i for i,r in enumerate(p.rows) if r[15]),next(i for i,r in enumerate(p.rows) if r[17])))
        self.assertEqual(first_valid[0],first_valid[1])

    def test_seed_reproducibility_and_master_holds_valid_payload(self):
        rows=AXI.random_vectors(17,100,2)
        self.assertEqual(rows,AXI.random_vectors(17,100,2))
        self.assertNotEqual(rows,AXI.random_vectors(18,100,2))
        held={1:0,4:0,7:0}
        for sequence in (rows,AXI.boundary_vectors(2)):
            for previous,current in zip(sequence,sequence[1:]):
                if not (previous[0] and current[0]):continue
                for valid,ready,payload in ((1,12,slice(1,4)),(4,13,slice(4,7)),(7,14,slice(7,10))):
                    if previous[valid] and not previous[ready]:
                        self.assertEqual(previous[payload],current[payload]);held[valid]+=1
        self.assertTrue(all(held.values()),held)

    def test_random_contains_partial_reset_and_long_backpressure(self):
        rows=AXI.random_vectors(17,100,2)
        aw=w=False;partial_reset=False
        for row in rows:
            if not row[0]:
                partial_reset|=aw ^ w;aw=w=False
            else:
                aw|=bool(row[1] and row[12]);w|=bool(row[4] and row[13])
                if row[15] and row[10]:aw=w=False
        self.assertTrue(partial_reset)

        run=longest=0
        for row in rows:
            run=run+1 if row[17] and not row[11] else 0
            longest=max(longest,run)
        self.assertGreater(longest,3)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_both_delays_mutations_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-axi',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,AXI.CONFIGS,39,12)
            for name in AXI.CONFIGS:
                c=read_json(out/f'{name}-boundaries/result.json')['counts']
                self.assertEqual(c['write_errors'],3);self.assertEqual(c['read_errors'],2)
                self.assertGreater(c['b_stalls'],0);self.assertGreater(c['r_stalls'],0)

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_each_demo_fault_fails_normal_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                with self.subTest(mutation=mutation):
                    out=Path(tmp)/f'm{mutation}'
                    p=run_example('local-axi',out,'--configuration','delay2','--iterations','2','--demo-bug',str(mutation))
                    self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                    self.assertFalse(read_json(out/'summary.json')['success'])
                    self.assertEqual(read_json(out/'delay2-boundaries/result.json')['status'],'fail')


if __name__=='__main__':unittest.main()
