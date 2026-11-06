import importlib.util
from pathlib import Path
import unittest
HERE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('guard_cases_test',HERE/'cases.py');C=importlib.util.module_from_spec(spec);spec.loader.exec_module(C);M=C.M
PARS=[dict(DATA_ID=0xa12f),dict(DATA_ID=0x35c9)]
class GuardTests(unittest.TestCase):
    def test_crc_catalogue_check_value(self):
        self.assertEqual(M.crc8(b'123456789'),0x4b);self.assertEqual(M.crc8(b''),0)
    def test_every_single_bit_corruption_is_rejected(self):
        packet=M.frame(0xa12f,0,0x5678)
        for bit in range(48):
            g=M.Guard(0xa12f);o=g.step(1,0,1,packet^(1<<bit),1)
            self.assertEqual(o[3:],[0,1,1]);self.assertIsNone(g.pending);self.assertEqual(g.expected,0)
    def test_identity_is_checked_even_with_a_valid_crc(self):
        g=M.Guard(0xa12f);self.assertEqual(g.step(1,0,1,M.frame(0x35c9,0,42),1)[3:],[0,1,2]);self.assertEqual(g.expected,0)
        self.assertEqual(g.step(1,0,1,M.frame(0xa12f,0,42),1)[1:],[1,42,1,0,0])
    def test_identity_outranks_a_wrong_counter(self):
        g=M.Guard(0xa12f);self.assertEqual(g.step(1,0,1,M.frame(0x35c9,7,42),1)[3:],[0,1,2]);self.assertEqual(g.expected,0)
        rows,out,_=C.make('corruption-identity',PARS[0]);self.assertIn(2,[o[5] for o,r in zip(out,rows) if (r[3]>>24)&255 not in (0,1)])
    def test_counter_wrap_and_replay_do_not_resynchronize(self):
        g=M.Guard(0xa12f)
        for counter in range(257):self.assertEqual(g.step(1,0,1,M.frame(0xa12f,counter%256,99),1)[3],1)
        self.assertEqual(g.expected,1)
        for bad in (0,2,255):self.assertEqual(g.step(1,0,1,M.frame(0xa12f,bad,99),1)[5],3);self.assertEqual(g.expected,1)
    def test_stall_keeps_payload_and_counter_until_handshake(self):
        g=M.Guard(0xa12f);g.step(1,0,1,M.frame(0xa12f,0,17),1)
        packet=M.frame(0xa12f,1,23)
        for _ in range(8):self.assertEqual(g.step(1,0,1,packet,0),[0,1,17,0,0,0]);self.assertEqual(g.expected,1)
        self.assertEqual(g.step(1,0,1,packet,1),[1,1,23,1,0,0])
    def test_flush_cancels_and_requires_counter_zero(self):
        g=M.Guard(0xa12f);g.step(1,0,1,M.frame(0xa12f,0,17),1)
        self.assertEqual(g.step(1,1,1,M.frame(0xa12f,1,23),1),[0,0,0,0,0,0]);self.assertEqual(g.expected,0)
        self.assertEqual(g.step(1,0,1,M.frame(0xa12f,1,23),1)[5],3)
    def test_campaign_completion_accounting(self):
        for p in PARS:
            for name in C.NAMES:
                rows,out,n=C.make(name,p);self.assertEqual(n['rows'],len(rows));self.assertEqual(len(rows),len(out));self.assertEqual(n['inputs'],n['validated']+n['rejected']);self.assertEqual(n['validated'],n['retired']+n['cancelled']);self.assertEqual(out[-1][1],0)
    def test_seed_reproduction_and_stalled_driver(self):
        a=C.make('random',PARS[0],17);self.assertEqual(a,C.make('random',PARS[0],17));self.assertNotEqual(a[0],C.make('random',PARS[0],18)[0])
        for before,after,expected in zip(a[0],a[0][1:],a[1]):
            if before[0] and not before[1] and before[2] and not expected[0] and after[0] and not after[1]:self.assertEqual(before[2:4],after[2:4])
    def test_input_ranges_are_not_truncated(self):
        g=M.Guard(0xa12f)
        for args in ((1,0,1,1<<48,1),(1,2,0,0,1),(1,0,0,-1,1)):
            with self.assertRaises(ValueError):g.step(*args)
        with self.assertRaises(ValueError):M.frame(0xa12f,256,0)
if __name__=='__main__':unittest.main()
