from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-plic')


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-plic'
    GOALS = 12

    def test_threshold_boundary_is_strict(self):
        p = P.Plan(4)
        p.write(0, 3)  # source 0 priority 3
        p.write(1, 3)  # threshold 3: equal is not a candidate
        p.fire(0)
        p.read(2)
        self.assertEqual(p.rows[-1][6], 0)
        self.assertEqual(p.rows[-1][7], 0)
        p.write(1, 2)
        p.read(2)
        self.assertEqual(p.rows[-1][6], 1)

    def test_tie_claims_the_lower_source(self):
        p = P.Plan(4)
        p.write(0, (5 << 3) | 5)
        p.fire(1)
        p.fire(0)
        p.read(2)
        self.assertEqual(p.rows[-1][6], 1)
        p.step()
        self.assertEqual(p.rows[-1][9] & 1, 1)

    def test_complete_only_releases_in_service_sources(self):
        p = P.Plan(4)
        p.step(rst=0)
        p.write(0, 7)
        p.fire(0)
        p.write(3, 1)  # never claimed: ignoring must not clear anything
        p.read(2)
        self.assertEqual(p.rows[-1][6], 1)
        p.write(3, 7)  # out of range with NS=4 is ignored
        p.write(3, 0x11)  # an out-of-range ID with the same low nibble
        p.step()
        self.assertEqual(p.rows[-1][9], 1)
        result = simulate_vectors(P, p.rows, {'NS': 4})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_refire_during_claim_survives_and_releases_once(self):
        for parameters in P.CONFIGS.values():
            p = P.Plan(parameters['NS'])
            p.write(0, 7)
            p.fire(0)
            p.step(psel=1, pwrite=0, reg=2, set_mask=1)  # claim while a new fire arrives
            self.assertEqual(p.rows[-1][8], 1)  # pending stays for the new event
            p.step()
            self.assertEqual(p.rows[-1][9], 1)  # and the claim put it in service
            p.write(3, 1)
            p.read(2)
            self.assertEqual(p.rows[-1][6], 1)  # the re-pended event is claimable

    def test_irq_tracks_candidates_not_raw_pending(self):
        p = P.Plan(4)
        p.write(0, 7)
        p.fire(0)
        p.read(2)  # claim clears pending but keeps service open
        self.assertEqual(p.rows[-1][7], 1)  # the claim itself still saw the candidate
        p.step()
        self.assertEqual(p.rows[-1][7], 0)  # in service with no pending is not an IRQ

    def test_claim_during_service_is_detected_on_the_pins(self):
        p = P.Plan(4)
        p.step(rst=0)
        p.write(0, 7)
        p.fire(0)
        p.read(2)
        p.write(3, 1)
        p.step()
        baseline = simulate_vectors(P, p.rows)
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        result = simulate_vectors(P, p.rows,
                                  replacements={'plic.sv': [
                                      ('else next_inservice = next_inservice & ~complete_bit;',
                                       'else next_inservice = next_inservice;')]})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('CHECK_FAIL PLIC_STATE', result.stdout)


if __name__ == '__main__':
    unittest.main()
