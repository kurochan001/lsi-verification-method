import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import assert_evidence, load_example, read_json, run_example, simulate_vectors

EXAMPLE = 'local-reset-x-formal'
P = load_example(EXAMPLE)
M = P.MODEL
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reset_x_formal', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
READY, VALID, DATA, ODD, COUNT, ERR, MASK, BITS, INIT = range(6, 15)


def label(result):
    return re.findall(r'^CHECK_FAIL (\w+)$', result.stdout, re.M)


class ModelTests(unittest.TestCase):
    def test_the_first_cycle_must_be_a_reset_and_data_must_fit(self):
        with self.assertRaises(ValueError):
            M.Model(8, 3).cycle(in_valid=1)
        m = M.Model(4, 2)
        m.cycle(rst=1)
        with self.assertRaises(ValueError):
            m.cycle(in_valid=1, in_data=16)

    def test_ready_rises_stages_minus_one_edges_after_the_reset(self):
        for stages in (2, 3, 4):
            m = M.Model(8, stages)
            ready = [m.cycle(rst=1)[READY]] + [m.cycle()[READY] for _ in range(stages)]
            self.assertEqual(ready, [0] * (stages - 1) + [1, 1])

    def test_valid_bits_become_known_one_stage_per_edge(self):
        m = M.Model(8, 3)
        masks = [m.cycle(rst=1)[MASK], m.cycle()[MASK], m.cycle()[MASK]]
        self.assertEqual(masks, [0b001, 0b011, 0b111])
        self.assertEqual(m.rows[-1][BITS], 0)
        m.cycle(rst=1)                          # a later reset loses nothing that was known
        self.assertEqual(m.rows[-1][MASK], 0b111)

    def test_an_item_leaves_after_the_pipeline_with_its_parity(self):
        m = M.Model(8, 3)
        m.cycle(rst=1), m.cycle(), m.cycle()
        m.cycle(in_valid=1, in_data=0b0111)
        self.assertEqual([m.cycle()[VALID], m.cycle()[VALID]], [0, 1])
        self.assertEqual(m.rows[-1][DATA:COUNT + 1], [7, 1, 0])
        self.assertEqual(m.cycle()[COUNT], 1)   # counted on the edge after the output
        self.assertEqual(m.counts['outputs'], 1)

    def test_an_input_during_the_flush_is_refused_and_remembered_until_reset(self):
        m = M.Model(8, 3)
        m.cycle(rst=1)
        self.assertEqual(m.cycle(in_valid=1, in_data=9)[ERR], 1)
        self.assertEqual([m.cycle()[ERR] for _ in range(6)], [1] * 6)
        self.assertEqual(m.rows[-1][VALID:COUNT + 1], [0, 0, 0, 0])      # the refused item never appears
        self.assertEqual(m.cycle(rst=1)[ERR], 0)
        self.assertEqual(m.counts, dict(outputs=0, resets=2, refused=1))

    def test_step_two_and_wrap(self):
        m = M.Model(4, 2)
        m.cycle(rst=1), m.cycle()
        m.cycle(cfg_we=1, cfg_step2=1)
        for _ in range(9):
            m.cycle(in_valid=1, in_data=1)
        m.cycle(), m.cycle()
        self.assertEqual(m.rows[-1][COUNT], 18 % 16)
        self.assertEqual(m.cycle(rst=1)[COUNT], 0)
        m.cycle(), m.cycle(in_valid=1), m.cycle(), m.cycle(), m.cycle()
        self.assertEqual(m.rows[-1][COUNT], 1)  # the reset also cleared the step

    def test_reset_with_data_in_flight_hides_it(self):
        m = M.Model(8, 3)
        m.cycle(rst=1), m.cycle(), m.cycle()
        m.cycle(in_valid=1, in_data=5), m.cycle(in_valid=1, in_data=6)
        m.cycle(rst=1)
        self.assertEqual(m.rows[-1][BITS] & 0b110, 0b110)       # still in the pipeline
        later = [m.cycle() for _ in range(5)]
        self.assertEqual([row[VALID] for row in later], [0] * 5)
        self.assertEqual(later[-1][COUNT], 0)

    def test_power_rows_and_fixed_scenario(self):
        self.assertEqual(M.power_row(8, 3, M.ONES)[:8], [M.POWER, 3, 1, 7, 255, 15, 1, M.ONES])
        self.assertEqual(M.power_row(4, 2, M.MIXED)[:8], [M.POWER, 0, 1, 1, 5, 5, 1, M.MIXED])
        # with two stages, the first of the two items in flight is already at the output when the reset comes
        for width, stages, outputs in ((8, 3, 15), (4, 2, 16)):
            rows, counts = M.boundary(width, stages)
            self.assertEqual(M.boundary(width, stages, M.ZEROS)[0][1:], rows)   # the values do not depend on power-up
            self.assertEqual(counts, dict(outputs=outputs, resets=5, refused=1))
            resets = [i for i, r in enumerate(rows) if r[1]]
            first_output = next(i for i, r in enumerate(rows) if r[VALID])
            self.assertLess(first_output, resets[1])    # mutant 5 needs an output before the second reset
            self.assertTrue(any(r[ERR] for r in rows[:resets[1]]))
            self.assertTrue(all(len(r) == 15 for r in rows))

    def test_random_rows_reproduce(self):
        self.assertEqual(M.random_rows(8, 3, 5, 200), M.random_rows(8, 3, 5, 200))
        self.assertNotEqual(M.random_rows(8, 3, 5, 200), M.random_rows(8, 3, 6, 200))
        starts = {M.random_rows(8, 3, seed, 1)[0][0][0] for seed in range(30)}
        self.assertEqual(starts, {M.CYCLE, M.POWER})


class PlanTests(unittest.TestCase):
    def cases(self, profile='smoke', bug=0):
        args = SimpleNamespace(profile=profile, seed=17, iterations=5, demo_bug=bug)
        return P.make_cases(args, P.CONFIGS['stages3'])

    def test_seed_reproduction(self):
        first = self.cases()
        self.assertEqual(first, self.cases())
        args = SimpleNamespace(profile='smoke', seed=18, iterations=5, demo_bug=0)
        self.assertNotEqual(first, P.make_cases(args, P.CONFIGS['stages3']))

    def test_plan_separates_what_x_shows_from_what_it_hides(self):
        ids = [(c['id'], c['category'], c['expected_failure']) for c in self.cases()]
        self.assertEqual(ids[:5], [('boundaries-power-x', 'functional', None), ('boundaries-power-zeros', 'functional', None),
                                   ('boundaries-power-ones', 'functional', None), ('boundaries-power-mixed', 'functional', None),
                                   ('random-seed17', 'functional', None)])
        self.assertEqual(ids[5:], [
            ('detect-mutation1', 'mutation', 'RX_COUNT'), ('detect-mutation2', 'mutation', 'RX_ODD'),
            ('detect-mutation3', 'mutation', 'RX_READY'), ('detect-mutation6', 'mutation', 'RX_COUNT'),
            ('x-hides-mutation4', 'diagnostic', None), ('x-hides-mutation5', 'diagnostic', None),
            ('ones-hides-mutation4', 'diagnostic', None), ('ones-hides-mutation5', 'diagnostic', None),
            ('mixed-detect-mutation4', 'mutation', 'RX_ERR'), ('mixed-detect-mutation5', 'mutation', 'RX_COUNT')])
        self.assertEqual(len(self.cases('nightly')), len(ids) + 2)
        self.assertEqual(set(P.LABELS) | set(P.HIDDEN), set(range(1, P.MUTANTS + 1)))

    def test_requirements_name_twenty_one_goals(self):
        data = json.loads((HERE / 'requirements.json').read_text())
        goals = [g for r in data['requirements'] for g in r['goals']]
        self.assertEqual((len(goals), len(set(goals)), len(data['requirements'])), (21, 21, 6))
        text = (HERE / 'tb/reset_x_tb.sv').read_text()
        self.assertEqual(set(re.findall(r'COVER ([a-z0-9/-]+)', text)), set(goals))


class CheckerTests(unittest.TestCase):
    PARAMETERS = P.CONFIGS['stages3']

    def run_rows(self, edit=None, replacements=None, power=None):
        rows = [list(r) for r in M.boundary(8, 3, power)[0]]
        if edit:
            edit(rows)
        return simulate_vectors(P, rows, self.PARAMETERS, replacements)

    def test_unchanged_rows_pass_from_every_power_up(self):
        for power in (None, M.ZEROS, M.ONES, M.MIXED):
            result = self.run_rows(power=power)
            self.assertEqual((result.returncode, label(result)), (0, []), result.stdout[-400:])

    def test_each_wrong_expectation_has_its_own_label(self):
        def flip(column, pick):
            def edit(rows):
                next(r for r in rows if pick(r))[column] ^= 1
            return edit
        valid = lambda r: r[VALID]
        expected = [(READY, lambda r: True, 'RX_READY'), (VALID, lambda r: r[READY], 'RX_VALID'), (DATA, valid, 'RX_DATA'),
                    (ODD, valid, 'RX_ODD'), (COUNT, lambda r: True, 'RX_COUNT'), (ERR, lambda r: True, 'RX_ERR'),
                    (BITS, lambda r: True, 'RX_REG'), (INIT, lambda r: True, 'RX_REG')]
        for column, pick, name in expected:
            with self.subTest(column=column):
                self.assertEqual(label(self.run_rows(flip(column, pick))), [name])

    def test_unknown_data_is_accepted_only_while_nothing_is_valid(self):
        result = self.run_rows()
        self.assertIn('COVER data/unknown-hidden', result.stdout)
        self.assertIn('COVER power/x', result.stdout)
        # the same unknown data, shown as valid, is an error
        shown = {'reset_x_unit.sv': [('assign out_valid = v[STAGES-1] && ready;', "assign out_valid = ready;")]}
        self.assertEqual(label(self.run_rows(replacements=shown)), ['RX_VALID'])

    def test_the_last_valid_bit_without_its_mask_is_unknown_after_a_one_cycle_reset(self):
        edit = {'reset_x_unit.sv': [('assign out_valid = v[STAGES-1] && ready;', 'assign out_valid = v[STAGES-1];')]}
        self.assertEqual(label(self.run_rows(replacements=edit)), ['RX_VALID'])

    def test_a_data_register_written_without_its_valid_bit_is_not_seen_by_simulation(self):
        # Harmless here: the data is hidden by out_valid. Listed so that the limit is explicit.
        edit = {'reset_x_unit.sv': [('if (v[g-1]) d[g*WIDTH +: WIDTH]', 'if (1) d[g*WIDTH +: WIDTH]')]}
        self.assertEqual(label(self.run_rows(replacements=edit)), [])

    def test_a_valid_bit_without_reset_is_reported_as_a_register(self):
        edit = {'reset_x_unit.sv': [('v[0] <= accept && !rst;', 'v[0] <= rst ? v[0] : accept;')]}
        self.assertEqual(label(self.run_rows(replacements=edit)), ['RX_REG'])


class RunnerTests(unittest.TestCase):
    def test_real_rtl_all_configurations_mutants_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example(EXAMPLE, out, '--iterations', '3')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            assert_evidence(self, out, P.CONFIGS, 21, 15 * len(P.CONFIGS), diagnostics=4 * len(P.CONFIGS), mutants=6)
            for name in P.CONFIGS:
                for m in P.HIDDEN:
                    self.assertEqual(read_json(out / f'{name}-x-hides-mutation{m}/result.json')['status'], 'pass')
                    self.assertEqual(read_json(out / f'{name}-mixed-detect-mutation{m}/result.json')['status'], 'detected')

    def test_demo_faults_fail_the_regression_where_the_plan_says(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run_example(EXAMPLE, out, '--configuration', 'stages2', '--iterations', '2', '--demo-bug', str(fault))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    status = lambda power: read_json(out / f'stages2-boundaries-power-{power}/result.json')['status']
                    hidden = fault in P.HIDDEN
                    self.assertEqual((status('x'), status('ones'), status('mixed')),
                                     ('pass', 'pass', 'fail') if hidden else ('fail', 'fail', 'fail'))


class FormalPlanTests(unittest.TestCase):
    def test_plan_and_properties_match_the_wrapper(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['known-proof', 'value-proof', 'scenario-cover'] +
                         [f'known-detect-mutation{m}' for m in range(1, 6)] +
                         ['value-detect-mutation3', 'value-detect-mutation6', 'known-misses-mutation6'])
        self.assertEqual([(c['mode'], c['depth']) for c in plan[:3]],
                         [('prove', F.PROOF_DEPTH), ('prove', F.PROOF_DEPTH), ('cover', F.BOUND)])
        self.assertEqual(F.plan(F.BOUND, 3)[0]['parameters'], {'MUTATION': 3, 'VALUES': 0})
        text = (HERE / 'reset_x_formal.sv').read_text()
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.KNOWN | F.VALUE | F.COVERS)
        self.assertFalse(F.KNOWN & F.VALUE)
        self.assertNotRegex(text, r'\bassume\s*\(')       # nothing is assumed, not even a first reset
        self.assertNotRegex(text, r'(?m)^\s*initial\b')

    def test_no_register_of_the_design_has_an_initial_value(self):
        text = (HERE / 'rtl/reset_x_unit.sv').read_text()
        self.assertNotRegex(text, r'(?m)^\s*initial\b')
        self.assertNotRegex(text, r'(?m)^\s*reg\b[^;]*=')

    def test_formal_finds_what_simulation_from_x_hides_and_needs_values_for_a_wrong_reset_value(self):
        self.assertTrue(set(P.HIDDEN) <= set(F.KNOWN_FAILURES))
        self.assertTrue(set(F.KNOWN_FAILURES.values()) <= F.KNOWN)
        self.assertTrue(set(F.VALUE_FAILURES.values()) <= F.VALUE)
        self.assertNotIn(6, F.KNOWN_FAILURES)
        last = F.plan(F.BOUND, 0)[-1]
        self.assertEqual((last['expect'], last['category'], last['parameters']), ('PASS', 'diagnostic', {'MUTATION': 6, 'VALUES': 0}))
        self.assertEqual(set(F.KNOWN_FAILURES) | set(F.VALUE_FAILURES), set(range(1, P.MUTANTS + 1)))
        self.assertEqual(F.CONFIGS, P.CONFIGS)
        self.assertEqual(F.properties({}, last)['assume'], set())


if __name__ == '__main__':
    unittest.main()
