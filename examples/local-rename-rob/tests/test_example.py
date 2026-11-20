import importlib.util
from pathlib import Path
import re
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-rename-rob')
M = P.MODEL
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rename_rob_formal', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
SIZES = [P.sizes(parameters) for parameters in P.CONFIGS.values()]


def label(result):
    return re.findall(r'^CHECK_FAIL (\w+)$', result.stdout, re.M)


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-rename-rob'
    GOALS = 17


class ModelTests(unittest.TestCase):
    def test_room_is_the_smaller_of_buffer_and_spare_registers(self):
        self.assertEqual([M.Model(*size).capacity for size in SIZES], [4, 3])
        for size in SIZES:
            m = M.Model(*size)
            accepted = [m.alloc(0) for _ in range(m.capacity + 2)]
            self.assertEqual(accepted, list(range(m.capacity)) + [None, None])
            self.assertEqual([row[3] for row in m.rows[1:]], [1] * m.capacity + [0, 0])

    def test_state_is_that_of_sequential_execution(self):
        m = M.Model(4, 10, 4)
        a, b, c = m.alloc(1), m.alloc(1), m.alloc(2)
        m.done(c, 7)
        m.done(b, 6)
        self.assertEqual(m.commit(), M.NONE)       # a is the head and has not completed
        m.done(a, 5)
        self.assertEqual([m.commit(), m.commit(), m.commit()], [M.RETIRE] * 3)
        self.assertEqual(m.state, [0, 6, 7, 0])
        self.assertEqual(m.counts['retires'], 3)

    def test_flush_keeps_the_named_instruction_and_marks_a_shared_register(self):
        m = M.Model(4, 10, 4)
        a, b, c = m.alloc(1), m.alloc(2), m.alloc(1)
        m.flush(a)
        self.assertEqual([i['id'] for i in m.flight], [a])
        self.assertEqual(m.rows[-1][:3], [M.FLUSH, a, 1])
        self.assertEqual(m.rows[-1][5], M.F_CANCEL | M.F_SAME_DST)
        m.flush(a)
        self.assertEqual(m.rows[-1][5], M.F_NOTHING)
        m.done(b, 9)                                 # cancelled: ignored
        self.assertEqual(m.rows[-1][5], M.F_IGNORED)
        self.assertIsNotNone(m.alloc(3))
        with self.assertRaises(ValueError):          # the place of c may belong to the new instruction
            m.done(c, 9)

    def test_exception_cancels_itself_and_everything_younger(self):
        m = M.Model(4, 10, 4)
        a, b = m.alloc(1), m.alloc(2)
        m.done(b, 3)
        m.done(a, 4, exc=True)
        self.assertEqual(m.commit(), M.TRAP)
        self.assertEqual(m.rows[-1][5], M.F_YOUNGER)
        self.assertEqual((m.flight, m.state, m.counts['traps'], m.counts['retires']), ([], [0, 0, 0, 0], 1, 0))

    def test_allocation_beside_a_retirement_sees_the_room_before_it(self):
        m = M.Model(4, 7, 8)
        first = m.alloc(0)
        while m.room():
            m.alloc(1)
        m.done(first, 1)
        self.assertIsNone(m.commit_and_alloc(2))
        self.assertEqual(len(m.flight), m.capacity - 1)
        with self.assertRaises(ValueError):          # the new head has not completed
            m.commit_and_alloc(2)

    def test_fixed_scenario_has_what_each_mutant_needs(self):
        for size in SIZES:
            rows, counts = M.boundary(*size)
            flags = lambda op: [r[5] for r in rows if r[0] == op]
            self.assertTrue(any(f & M.F_SAME_DST for f in flags(M.FLUSH)))          # mutants 1, 3 and 5
            self.assertTrue(any(r[0] == M.ALLOC and r[3] == 0 for r in rows))       # mutant 4
            commits = [r for r in rows if r[0] == M.COMMIT]
            self.assertEqual(commits[0][1], M.RETIRE)                               # mutant 2
            self.assertTrue(any(r[1] == M.TRAP and r[5] & M.F_YOUNGER for r in commits))  # mutant 6
            self.assertEqual({r[3] for r in rows if r[0] == M.BOTH}, {0, 1})
            self.assertEqual(counts, dict(steps=len(rows), allocs=12, retires=6, traps=2, flushes=2))

    def test_random_rows_reproduce_and_keep_the_contract(self):
        self.assertEqual(M.random_rows(4, 7, 8, 5, 400), M.random_rows(4, 7, 8, 5, 400))
        self.assertNotEqual(M.random_rows(4, 7, 8, 5, 400), M.random_rows(4, 7, 8, 6, 400))
        for seed in range(20):                       # no completion for a place that may have been reused
            rows, counts = M.random_rows(4, 10, 4, seed, 300)
            self.assertGreaterEqual(counts['steps'], 300)


class CheckerTests(unittest.TestCase):
    """Checks that no mutant reaches first: each must fire on its own."""
    PARAMETERS = P.CONFIGS['rob4']

    def run_rows(self, edit=None, replacements=None):
        rows = [list(r) for r in M.boundary(*P.sizes(self.PARAMETERS))[0]]
        if edit:
            edit(rows)
        return simulate_vectors(P, rows, self.PARAMETERS, replacements)

    def test_unchanged_rows_pass(self):
        result = self.run_rows()
        self.assertEqual((result.returncode, label(result)), (0, []), result.stdout[-400:])

    def test_wrong_retired_value_and_wrong_committed_state_are_told_apart(self):
        def retired(rows):
            next(r for r in rows if r[0] == M.COMMIT and r[1] == M.RETIRE)[3] ^= 1
        def state(rows):
            [r for r in rows if r[0] == M.READ and r[2]][0][2] ^= 1
        self.assertEqual(label(self.run_rows(retired)), ['RR_VALUE'])
        self.assertEqual(label(self.run_rows(state)), ['RR_STATE'])

    def test_wrong_expectations_of_order_room_and_flush_are_reported(self):
        def order(rows):
            next(r for r in rows if r[0] == M.COMMIT and r[1] == M.RETIRE)[2] ^= 1
        def room(rows):
            next(r for r in rows if r[0] == M.ALLOC)[3] = 0
        def flush(rows):
            next(r for r in rows if r[0] == M.FLUSH)[2] += 1
        def trap(rows):
            next(r for r in rows if r[0] == M.COMMIT and r[1] == M.RETIRE)[1] = M.TRAP
        self.assertEqual(label(self.run_rows(order)), ['RR_RETIRE'])
        self.assertEqual(label(self.run_rows(room)), ['RR_READY'])
        self.assertEqual(label(self.run_rows(flush)), ['RR_FLUSH'])
        self.assertEqual(label(self.run_rows(trap)), ['RR_TRAP'])

    def test_a_second_completion_that_is_not_ignored_is_seen_in_the_value(self):
        edit = {'rename_rob.sv': [('if (done_valid && done_live && !rob_done[done_tag]) begin',
                                   'if (done_valid && done_live) begin')]}
        self.assertEqual(label(self.run_rows(replacements=edit)), ['RR_VALUE'])

    def test_a_walk_that_never_ends_and_a_reset_that_keeps_instructions_are_reported(self):
        stuck = {'rename_rob.sv': [("            end else if (walking) begin\n                walking <= 1'b0;",
                                    "            end else if (walking) begin\n                walking <= 1'b1;")]}
        self.assertEqual(label(self.run_rows(replacements=stuck)), ['RR_WALK'])
        kept = {'rename_rob.sv': [("walking <= 1'b0; count <= {RW+1{1'b0}}; head", "walking <= 1'b0; head")]}
        self.assertIn(label(self.run_rows(replacements=kept)), (['RR_X'], ['RR_RESET']))

    def test_a_free_list_that_starts_with_a_mapped_register_is_a_double_owner(self):
        edit = {'rename_rob.sv': [('free[i] <= i >= LREGS;', 'free[i] <= i >= LREGS - 1;')]}
        self.assertEqual(label(self.run_rows(replacements=edit)), ['RR_DOUBLE'])


class FormalPlanTests(unittest.TestCase):
    def test_plan_and_properties_match_the_rtl(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['conservation-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 7)])
        self.assertEqual((plan[0]['mode'], plan[0]['depth']), ('prove', F.PROOF_DEPTH))
        self.assertEqual(F.plan(F.BOUND, 3)[0]['parameters'], {'MUTATION': 3})
        text = (HERE / 'rtl/rename_rob.sv').read_text()
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.ASSERTS | F.COVERS | {'as_initial_reset'})
        self.assertTrue(set(F.FAILURES.values()) <= F.PROPERTIES)
        self.assertEqual(set(F.FAILURES), set(P.LABELS))

    def test_proved_sizes_are_stated_and_differ_from_the_larger_simulated_buffer(self):
        self.assertEqual({name: c['ROB'] for name, c in F.CONFIGS.items()}, {'rob4': 4, 'free3': 4})
        self.assertEqual(P.CONFIGS['free3-rob8']['ROB'], 8)
        self.assertEqual(F.CONFIGS['rob4'], P.CONFIGS['rob4'])
        for c in F.CONFIGS.values():
            self.assertGreater(c['PREGS'], c['LREGS'])


if __name__ == '__main__':
    unittest.main()
