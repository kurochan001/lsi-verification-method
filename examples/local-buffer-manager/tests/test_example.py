import importlib.util
from pathlib import Path
import re
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-buffer-manager')
M = P.MODEL
HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('buffer_manager_formal', HERE / 'formal.py')
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)


def label(result):
    return re.findall(r'^CHECK_FAIL (\w+)$', result.stdout, re.M)


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-buffer-manager'
    GOALS = 17


class ModelTests(unittest.TestCase):
    def test_free_list_is_first_in_first_out_and_released_buffers_go_last(self):
        m = M.Model(4, 2)
        self.assertEqual([m.cycle(enq=0)[0] for _ in range(3)], [0, 1, 2])
        _, taken, _ = m.cycle(deq=0)
        self.assertEqual(taken, 0)
        self.assertTrue(m.cycle(rel=0)[2])
        self.assertEqual(m.free, [3, 0])
        self.assertEqual(m.place(0), 'free')
        self.assertEqual((m.place(1), m.place(2)), ('queue0', 'queue0'))

    def test_only_a_held_buffer_is_released(self):
        m = M.Model(4, 2)
        m.cycle(enq=1)
        self.assertFalse(m.cycle(rel=0)[2])          # in queue 1
        self.assertFalse(m.cycle(rel=3)[2])          # free
        _, b, _ = m.cycle(deq=1)
        self.assertTrue(m.cycle(rel=b)[2])
        self.assertFalse(m.cycle(rel=b)[2])          # a second release
        self.assertEqual(m.counts['refused'], 3)
        flags = [r[-1] for r in m.rows]
        self.assertTrue(flags[2] & M.FLAG['release/queued'] and flags[3] & M.FLAG['release/twice'])

    def test_operations_of_one_cycle_see_the_state_at_its_start(self):
        m = M.Model(4, 2)
        m.cycle(enq=0)
        new, old, _ = m.cycle(enq=0, deq=0)          # the only buffer leaves, a new one comes
        self.assertEqual((new, old, m.queues[0]), (1, 0, [1]))
        self.assertTrue(m.rows[-1][-1] & M.FLAG['same/one'])
        m.cycle(enq=1)
        m.cycle(enq=1)                               # the free list is empty now
        self.assertEqual(m.free, [])
        new, _, released = m.cycle(enq=0, rel=0)     # refused: a release does not refill this cycle
        self.assertEqual((new, released, m.free), (None, True, [0]))
        new, _, _ = m.cycle(enq=0, rel=None)
        self.assertEqual(new, 0)

    def test_every_buffer_is_in_exactly_one_place_in_random_rows(self):
        for seed in range(30):
            m = M.Model(8, 2)
            rows, _ = M.random_rows(8, 2, seed, 200)
            self.assertGreaterEqual(len(rows), 200)
            m2 = M.Model(8, 2)
            for _ in range(50):
                m2.cycle(enq=seed % 2, deq=(seed + 1) % 2, rel=sorted(m2.held)[0] if m2.held else None)
                places = sorted(m2.free + [b for q in m2.queues for b in q] + sorted(m2.held))
                self.assertEqual(places, list(range(8)))

    def test_fixed_scenario_reaches_every_goal_and_what_each_mutant_needs(self):
        for nb, nq in (P.sizes(c) for c in P.CONFIGS.values()):
            rows, counts = M.boundary(nb, nq)
            seen = {g for r in rows for g, f in M.FLAG.items() if r[-1] & f}
            self.assertEqual(seen, set(M.GOALS))
            self.assertEqual(len(M.GOALS), ExampleTests.GOALS)
            self.assertEqual(counts['steps'], len(rows))
            self.assertTrue(all(len(r) == M.COLUMNS for r in rows))

    def test_random_rows_reproduce(self):
        self.assertEqual(M.random_rows(16, 4, 5, 300), M.random_rows(16, 4, 5, 300))
        self.assertNotEqual(M.random_rows(16, 4, 5, 300), M.random_rows(16, 4, 6, 300))


class CheckerTests(unittest.TestCase):
    """Each check fires on its own, with the label the plan expects."""
    PARAMETERS = P.CONFIGS['b8-q2']

    def run_rows(self, edit=None, replacements=None):
        rows = [list(r) for r in M.boundary(*P.sizes(self.PARAMETERS))[0]]
        if edit:
            edit(rows)
        return simulate_vectors(P, rows, self.PARAMETERS, replacements)

    def first(self, rows, predicate):
        return next(r for r in rows if r[0] == M.CYCLE and predicate(r))

    def test_unchanged_rows_pass(self):
        result = self.run_rows()
        self.assertEqual((result.returncode, label(result)), (0, []), result.stdout[-400:])

    def test_wrong_expectations_are_told_apart(self):
        def full(rows):
            self.first(rows, lambda r: r[1])[7] ^= 1
        def empty(rows):
            self.first(rows, lambda r: r[3])[9] ^= 1
        def release(rows):
            self.first(rows, lambda r: r[5])[11] ^= 1
        def ident(rows):
            self.first(rows, lambda r: r[1] and r[7])[8] ^= 1
        def count(rows):
            self.first(rows, lambda r: r[1])[12] += 1
        for edit, expected in ((full, 'BM_FULL'), (empty, 'BM_EMPTY'), (release, 'BM_RELEASE'),
                               (ident, 'BM_ID'), (count, 'BM_COUNT')):
            with self.subTest(expected=expected):
                self.assertEqual(label(self.run_rows(edit)), [expected])

    def test_a_reset_that_keeps_a_buffer_held_is_a_double_place(self):
        edit = {'buffer_manager.sv': [("held <= {NB{1'b0}};", "held <= {{NB-1{1'b0}}, 1'b1};")]}
        self.assertEqual(label(self.run_rows(replacements=edit)), ['BM_DOUBLE'])

    def test_a_row_that_never_ends_has_its_own_label(self):
        edit = {'buffer_manager_tb.sv': [('limit = cycles + 8;', 'limit = cycles - 1;')]}
        self.assertEqual(label(self.run_rows(replacements=edit)), ['BM_TIMEOUT'])


class FormalPlanTests(unittest.TestCase):
    def test_plan_and_properties_match_the_rtl(self):
        plan = F.plan(F.BOUND, 0)
        self.assertEqual([c['id'] for c in plan], ['conservation-proof', 'scenario-cover'] +
                         [f'detect-mutation{m}' for m in range(1, 8)])
        self.assertEqual((plan[0]['mode'], plan[0]['depth']), ('prove', F.PROOF_DEPTH))
        self.assertEqual(F.plan(F.BOUND, 3)[0]['parameters'], {'MUTATION': 3})
        text = (HERE / 'rtl/buffer_manager.sv').read_text()
        labels = set(re.findall(r'\b((?:ap|ai|cp|as)_\w+):', text))
        self.assertEqual(labels, F.ASSERTS | F.COVERS | {'as_initial_reset'})
        self.assertTrue(set(F.FAILURES.values()) <= F.ASSERTS)
        self.assertEqual(set(F.FAILURES), set(P.LABELS))

    def test_proved_sizes_are_smaller_than_the_simulated_ones(self):
        for c in F.CONFIGS.values():
            self.assertLessEqual(c['NB'], 8)
        self.assertEqual(max(c['NB'] for c in P.CONFIGS.values()), 16)


if __name__ == '__main__':
    unittest.main()
