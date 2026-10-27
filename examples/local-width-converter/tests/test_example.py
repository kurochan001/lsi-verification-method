from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example
from system_test_support import SystemContract
P=load_example('local-width-converter')
class CircuitTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-width-converter';GOALS=15
    def test_error_does_not_roll_back_other_half(self):
        p=P.Plan();p.op(1,0,0x1122334455667788,error=4);p.op(2,0)
        self.assertEqual(p.rows[-1][8],0x55667788);self.assertEqual(p.rows[0][9],2)
    def test_zero_strobes_and_interrupted_write(self):
        p=P.Plan();p.op(1,0,0xffffffffffffffff,strb=0)
        self.assertEqual(p.rows[-1][-1],0);self.assertFalse(any(p.memory))
        p.op(3,0,0x12345678aabbccdd);p.op(2,0)
        self.assertEqual(p.rows[-1][8],0xaabbccdd)

    def simulate(self,plan,source=None):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);rtl=d/'adapter.sv';rtl.write_text(source or P.SOURCES[0].read_text())
            vectors=d/'vectors.txt';vectors.write_text(''.join(' '.join(format(v,'x') for v in r)+'\n' for r in plan.rows))
            built=subprocess.run(['iverilog','-g2012','-s','width_tb','-o',str(d/'sim.vvp'),str(rtl),str(P.SOURCES[1])],capture_output=True,text=True,timeout=10)
            self.assertEqual(built.returncode,0,built.stderr)
            return subprocess.run(['vvp',str(d/'sim.vvp'),'+VECTORS='+str(vectors),'+WAVE='+str(d/'wave.vcd')],capture_output=True,text=True,timeout=10)

    def test_response_must_use_matching_channel(self):
        original=P.SOURCES[0].read_text()
        wrong_read=original.replace('s_rvalid<=1;s_rdata<={m_rdata,read_buf[31:0]};s_rresp<=MUTATION==3 ? 0:rerror;',
            's_bvalid<=1;s_rdata<={m_rdata,read_buf[31:0]};s_bresp<=MUTATION==3 ? 0:rerror;')
        wrong_write=original.replace('s_bvalid<=1;s_bresp<=MUTATION==3 ? 0:werror;',
            's_rvalid<=1;s_rdata<=0;s_rresp<=MUTATION==3 ? 0:werror;')
        for corrupted in (wrong_read,wrong_write):
            self.assertNotEqual(corrupted,original)
            plan=P.Plan();plan.op(0);plan.op(1,0,0x1122334455667788);plan.op(2,0)
            r=self.simulate(plan,corrupted);self.assertNotEqual(r.returncode,0,r.stdout)
            self.assertIn('CHECK_FAIL WIDTH_CHANNEL',r.stdout)

    def test_interrupted_upper_only_write_matches_oracle(self):
        for strobe in (1,15,16,128,240,255):
            with self.subTest(strobe=strobe):
                plan=P.Plan();plan.op(0);plan.op(3,0,0x1122334455667788,strb=strobe);plan.op(2,0)
                r=self.simulate(plan);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
                self.assertIn('COVER reset/recovery',r.stdout)

    def test_order_coverage_uses_actual_handshakes(self):
        # This legal implementation waits for AW before accepting W, even
        # though the driver offers W first. It must not earn the W-first bin.
        original=P.SOURCES[0].read_text()
        serial=original.replace('assign s_wready=idle && !wfull;', 'assign s_wready=idle && !wfull && awfull;')
        self.assertNotEqual(serial,original)
        plan=P.Plan();plan.op(0);plan.op(1,0,0x12345678,awdelay=3)
        r=self.simulate(plan,serial);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('COVER request/aw-before-w',r.stdout)
        self.assertNotIn('COVER request/w-before-aw',r.stdout)

    def test_recovery_cover_requires_interrupted_operation(self):
        plan=P.Plan();plan.op(0);plan.op(2,32)
        r=self.simulate(plan);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertNotIn('COVER reset/recovery',r.stdout)

if __name__=='__main__':unittest.main()
