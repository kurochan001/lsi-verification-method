from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-retry-link')


class RetryTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-retry-link';GOALS=20

    def test_crc_all_messages_and_every_single_bit_error(self):
        if not (shutil.which('iverilog') and shutil.which('vvp')):self.skipTest('Icarus required')
        self.assertEqual([P.crc(x) for x in (0,1,256)],[0,7,21])
        for message in range(512):
            code=(message<<8)|P.crc(message)
            for bit in range(17):
                faulty=code^(1<<bit);self.assertNotEqual(faulty&255,P.crc(faulty>>8))
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp);tb=out/'tb.sv'
            tb.write_text('module tb;reg [8:0] message;wire [7:0] crc;integer i;crc9 dut(.*);initial begin for(i=0;i<512;i=i+1)begin message=9\'(i);#1;$display("%0d %0d",i,crc);end end endmodule')
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(out/'sim'),str(P.HERE/'rtl/crc9.sv'),str(tb)],capture_output=True,text=True,check=True,timeout=30)
            r=subprocess.run(['vvp',str(out/'sim')],capture_output=True,text=True,check=True,timeout=30)
            self.assertEqual([(int(a),int(b)) for a,b in (line.split() for line in r.stdout.splitlines())],[(x,P.crc(x)) for x in range(512)])

    def test_lost_ack_does_not_duplicate_application_delivery(self):
        p=P.Plan(3,2);p.cycle(rst=0);p.transfer(0xa5,'ack-loss')
        self.assertEqual((p.counts['inputs'],p.counts['outputs'],p.counts['successes'],p.counts['retries']),(1,1,1,1))
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_exhaustion_can_mean_delivered_or_not_delivered(self):
        for mode,outputs in (('lose-all',0),('ack-all',1)):
            p=P.Plan(3,2);p.cycle(rst=0);p.transfer(0x97,mode)
            self.assertEqual((p.failed,p.counts['outputs'],p.counts['failures']),(1,outputs,1))
            self.assertEqual(p.cycle(valid=1,data=0x98),0)
            p.cycle(rst=0);p.transfer(0x99)
            self.assertEqual(p.counts['outputs'],outputs+1)
            result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)

    def test_wire_backpressure_does_not_spend_retry_budget(self):
        p=P.Plan(3,2);p.cycle(rst=0);p.cycle(valid=1,data=0x55)
        for _ in range(30):p.cycle(valid=1,data=0xaa,line_ready=0)
        self.assertEqual((p.phase,p.retried,p.failed),(1,0,0))
        while not p.done:p.cycle()
        p.cycle();self.assertEqual(p.counts['outputs'],1)
        result=simulate_vectors(P,p.rows);self.assertEqual(result.returncode,0,result.stdout)


if __name__=='__main__':unittest.main()
