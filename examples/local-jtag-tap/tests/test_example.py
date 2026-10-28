from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-jtag-tap')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-jtag-tap'
    GOALS = 14

    def test_idcode_capture_and_ir_update(self):
        p = P.Plan(0x12345679)
        p.reset()
        p.clock(0)
        p.go_shift_dr()
        self.assertEqual(p.id_shift, 0x12345679)
        p.reset()
        p.clock(0)
        p.load_ir([1, 1, 1, 1])
        self.assertEqual(p.ir, P.BYPASS)

    def test_extest_drives_boundary_register(self):
        p = P.Plan(0x12345679)
        p.fixed()
        self.assertIn(0xa5, [row[6] for row in p.rows])

    def test_tlr_resets_state_and_instruction(self):
        p = P.Plan(0xdeadbeef)
        p.reset()
        self.assertEqual(p.state, P.TLR)
        self.assertEqual(p.ir, P.IDCODE_IR)


    def test_preload_and_extest_update_on_falling_edges_without_pin_glitches(self):
        for parameters in P.CONFIGS.values():
            p=P.Plan(parameters['IDCODE']);p.reset();p.clock(0)
            p.load_ir(p.bits(P.SAMPLE,4));p.boundary_scan(0x3c)
            p.load_ir(p.bits(P.EXTEST,4));p.step(tck=0)
            self.assertEqual(p.pin_out,0x3c)
            p.go_shift_dr()
            for i,bit in enumerate(p.bits(0xa5,8)):
                p.clock(tms=int(i==7),tdi=bit)
                self.assertEqual(p.pin_out,0x3c)
            p.clock(1);self.assertEqual(p.pin_out,0x3c)
            p.step(tck=0,tms=1);self.assertEqual(p.pin_out,0xa5)
            p.clock(0);p.load_ir(p.bits(P.IDCODE_IR,4));p.step(tck=0,pin_in=0x69)
            self.assertEqual(p.pin_out,0x69)
            result=simulate_vectors(P,p.rows,parameters)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_unimplemented_ir_selects_one_bit_bypass(self):
        p=P.Plan(0x12345679);p.reset();p.clock(0);p.load_ir(p.bits(8,4))
        p.shift_dr([1,0,1,1,0]);p.step(tck=0)
        result=simulate_vectors(P,p.rows,{'IDCODE':p.idcode})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(all(c['IDCODE']&1 for c in P.CONFIGS.values()))

    def test_five_tms_ones_reset_every_tap_state(self):
        from collections import deque
        p=P.Plan(0x12345679)
        for target in range(16):
            p.reset();p.clock(0)
            queue=deque([(P.RTI,[])]);visited=set()
            while queue:
                state,path=queue.popleft()
                if state==target:break
                if state in visited:continue
                visited.add(state)
                for tms in (0,1):queue.append((p.transition(state,tms),path+[tms]))
            for tms in path:p.clock(tms)
            self.assertEqual(p.state,target)
            for _ in range(5):p.clock(1)
            p.step(tck=0,tms=1)
            self.assertEqual((p.state,p.ir),(P.TLR,P.IDCODE_IR))
        result=simulate_vectors(P,p.rows,{'IDCODE':p.idcode})
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
