from pathlib import Path
import shutil, sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import assert_evidence, load_example, run_example, simulate_vectors

P = load_example('local-activation')
WRAP = {'pwl_activation.sv': [('MUTATION == 4 ? magnitude[10:0]', '1 ? magnitude[10:0]')]}


def accepted_inputs(rows):
    return [row[2] - (row[2] >> 11) * 4096 for row in rows if row[0] and row[1] and row[4]]


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-activation'
    GOALS = 14

    def test_real_rtl_all_configurations_and_mutants(self):
        # Two diagnostics per configuration run mutants 1 and 2 under the loose bound.
        if not (shutil.which('iverilog') and shutil.which('vvp')):
            self.skipTest('Icarus required')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example(self.EXAMPLE, out, '--iterations', '3')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            assert_evidence(self, out, P.CONFIGS, self.GOALS, 8 * len(P.CONFIGS), diagnostics=2 * len(P.CONFIGS))
            for name in P.CONFIGS:
                for mutation in (1, 2):
                    log = (out / f'{name}-loose-bound-mutation{mutation}' / 'simulation.log').read_text()
                    self.assertIn('RESULT PASS', log)

    def test_rows_carry_the_required_and_the_loose_bound(self):
        self.assertEqual({row[7] for row in P.boundary_vectors(0)}, {0, 320})
        self.assertEqual({row[7] for row in P.boundary_vectors(0, P.LOOSE)}, {0, 640})
        self.assertEqual(accepted_inputs(P.boundary_vectors(1))[:4096], list(P.INPUTS))

    def test_expected_values_come_from_the_exact_functions(self):
        for x in (1, 37, 511, 1024, 2047):
            self.assertAlmostEqual(P.ideal(0, -x), 1024 - P.ideal(0, x), places=9)
            self.assertAlmostEqual(P.ideal(1, -x), -P.ideal(1, x), places=9)
        self.assertEqual(P.ideal(0, 0), 512)
        self.assertEqual(P.ideal(1, 0), 0)

    def test_the_magnitude_wrap_is_visible_only_at_x_minus_2048(self):
        def rows(xs):
            p = P.Plan(0)
            p.cycle(rst=0)
            for x in xs:
                p.send(x)
            p.drain()
            return p.rows
        others = simulate_vectors(P, rows([x for x in P.INPUTS if x != -2048]), replacements=WRAP)
        self.assertIn('RESULT PASS', others.stdout)
        alone = simulate_vectors(P, rows([-2048]), replacements=WRAP)
        self.assertIn('CHECK_FAIL ACT_TOLERANCE', alone.stdout)

    def test_random_sampling_does_not_always_reach_x_minus_2048(self):
        self.assertIn(-2048, accepted_inputs(P.random_vectors(17, 300, 0)))
        for seed in (18, 19):
            self.assertNotIn(-2048, accepted_inputs(P.random_vectors(seed, 300, 0)))


if __name__ == '__main__':
    unittest.main()
