import hashlib
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import assert_evidence,load_example,read_json,run_example
BRIDGE=load_example('local-bus-bridge')


class BridgeTest(unittest.TestCase):
    def test_basic_read_only_and_wait_contract(self):
        m=BRIDGE.Basic(2);m.step(0,0,0,0,0,0)
        m.step(1,1,0,1,4,0xffffffff)
        self.assertEqual(m.step(1,1,1,1,4,0xffffffff)[:2],(0,0))
        self.assertEqual(m.step(1,1,1,1,4,0xffffffff)[:2],(0,0))
        self.assertEqual(m.step(1,1,1,1,4,0xffffffff),(1,1,0x41504233))
        self.assertEqual(m.value,0)

    def test_axi_buffers_write_data_before_address(self):
        p=BRIDGE.Plan(1,2);p.cycle(rst=0);p.cycle(wv=1,wd=0x12345678,ws=15)
        p.cycle(av=1,aa=0,wd=0xffffffff);p.idle(12)
        self.assertEqual(p.model.basic.value,0x12345678)
        self.assertTrue(p.model.bv)

    def test_axi_read_and_write_arbitrate_without_losing_either(self):
        p=BRIDGE.Plan(1,0);p.cycle(rst=0)
        p.cycle(av=1,aa=0,wv=1,wd=0x12345678,arv=1,ara=0)
        for _ in range(20):p.cycle(br=1,rr=1)
        accesses=[r for r in p.rows if r[27] and r[28] and r[32]]
        self.assertEqual([r[29] for r in accesses],[1,0])
        self.assertEqual(accesses[-1][34],0x12345678)
        self.assertFalse(p.model.bv or p.model.rv or p.model.ar_full)

    def test_unsupported_and_unmapped_requests_do_not_reach_apb(self):
        for bus in (0,1):
            p=BRIDGE.Plan(bus,2);p.cycle(rst=0)
            p.transfer(0,True,0xffffffff,mask=5,size=0);p.transfer(0x200)
            self.assertTrue(all(r[27]==0 for r in p.rows))
            self.assertEqual(p.model.basic.value,0)

    def test_reset_aborts_then_recovers_in_each_configuration(self):
        for bus in (0,1):
            for wait in (0,2):
                p=BRIDGE.Plan(bus,wait);p.cycle(rst=0)
                p.transfer(0,True,0xffffffff,abort=2)
                p.transfer(0,True,0x12345678);p.transfer(0)
                self.assertEqual(p.model.basic.value,0x12345678)

    def test_simultaneous_axi_responses_count_both_completions(self):
        p=BRIDGE.Plan(1,2);p.cycle(rst=0);p.overlap()
        simultaneous=[r for r in p.rows if r[22] and r[14] and r[24] and r[15]]
        self.assertEqual(len(simultaneous),1)
        totals=BRIDGE.counts(p.rows,1)
        self.assertEqual((totals['writes'],totals['reads'],totals['apb']),(1,1,2))

    def test_random_reproducible(self):
        self.assertEqual(BRIDGE.random_vectors(1,2,17,20),BRIDGE.random_vectors(1,2,17,20))
        self.assertNotEqual(BRIDGE.random_vectors(1,2,17,20),BRIDGE.random_vectors(1,2,18,20))

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_four_configurations_mutations_and_oracle_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out';p=run_example('local-bus-bridge',out)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            assert_evidence(self,out,BRIDGE.CONFIGS,18,24)
            manifest=read_json(out/'manifest.json')['source_sha256']
            path=BRIDGE.EXTRA_INPUTS[0]
            self.assertEqual(manifest['examples/local-apb-timer/run.py'],hashlib.sha256(path.read_bytes()).hexdigest())

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus required')
    def test_demo_faults_fail_normal_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1,5):
                out=Path(tmp)/str(mutation)
                p=run_example('local-bus-bridge',out,'--configuration','axi-wait2','--iterations','2','--demo-bug',str(mutation))
                self.assertEqual(p.returncode,1,p.stdout+p.stderr)
                self.assertEqual(read_json(out/'axi-wait2-boundaries/result.json')['status'],'fail')

if __name__=='__main__':unittest.main()
