from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example

P = load_example('local-secure-lifecycle')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-secure-lifecycle'
    GOALS = 15

    def test_nonsecure_write_has_no_side_effect(self):
        p = P.Plan(3, 0xa55a)
        p.step(rst=0)
        p.step(cs=1, we=1, addr=0x00, wdata=0x1234, secure=1)
        p.step(cs=1, we=1, addr=0x00, wdata=0x9999, secure=0)
        p.step(cs=1, re=1, addr=0x00, secure=1)
        self.assertEqual(p.rows[-2][11], 1)
        self.assertEqual(p.rows[-1][10], 0x1234)

    def test_tamper_zeroizes_keys_and_lockout_stops_debug(self):
        p = P.Plan(2, 0x5aa5)
        p.step(rst=0)
        p.step(cs=1, we=1, addr=0x00, wdata=0x1111, secure=1)
        p.step(tamper=1)
        p.step()
        p.step(cs=1, re=1, addr=0x00, secure=1)
        self.assertEqual(p.rows[-1][10], 0)
        p.step(rst=0)
        for _ in range(2):
            p.step(cs=1, we=1, addr=0x1c, debug_key=0xffff, secure=1)
        p.step(cs=1, we=1, addr=0x1c, debug_key=0x5aa5, secure=1)
        self.assertEqual(p.rows[-1][11], 1)
        self.assertTrue(p.lockout)


if __name__ == '__main__':
    unittest.main()
