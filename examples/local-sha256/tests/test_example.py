from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'local-common'))
from local_test_support import load_example,simulate_vectors
from system_test_support import SystemContract
P=load_example('local-sha256')

class ExampleTests(SystemContract,unittest.TestCase):
    EXAMPLE='local-sha256';GOALS=15
    def check_rtl(self,rows,parameters=None):
        r=simulate_vectors(P,rows,parameters=parameters)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_published_empty_and_abc_digests(self):
        p=P.Plan(1);p.cycle(rst=0)
        for message,expected in ((b'',0xe3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855),
                                 (b'abc',0xba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad)):
            p.message(message,hold=4)
            self.assertEqual(p.digest,expected)
        self.check_rtl(p.rows)

    def test_padding_and_chaining_boundaries(self):
        for rounds in (1,2):
            p=P.Plan(rounds);p.cycle(rst=0)
            for n in (54,55,56,57,63,64,65,118,119):p.message(bytes(range(n)),gaps=True)
            self.check_rtl(p.rows,{'ROUNDS':rounds})

    def test_rejection_does_not_consume_input_or_poison_next_message(self):
        p=P.Plan(1);p.cycle(rst=0);self.assertEqual(p.cycle(cmd=1,length=127),(1,0))
        for _ in range(5):
            self.assertEqual(p.cycle(cmd=1,length=0,valid=1,data=0xff,ready=0),(0,0))
        self.assertEqual((p.valid,p.error,p.digest),(1,1,0))
        p.cycle();p.message(b'recovered',hold=2);self.check_rtl(p.rows)

    def test_reset_cancels_partial_input_and_compression(self):
        p=P.Plan(1);p.cycle(rst=0);p.cycle(cmd=1,length=2);p.cycle(valid=1,data=0x41);p.cycle(rst=0)
        p.cycle(cmd=1,length=0)
        for _ in range(10):p.cycle()
        p.cycle(rst=0);p.message(b'abc');self.check_rtl(p.rows)
        p.cycle(cmd=1,length=1)
        r=simulate_vectors(P,p.rows);self.assertNotEqual(r.returncode,0);self.assertIn('CHECK_FAIL SHA_UNDRAINED',r.stdout)

if __name__=='__main__':unittest.main()
