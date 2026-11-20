from itertools import permutations
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors
from system_test_support import SystemContract

P = load_example('local-riscv-atomic')
L = P.L
ICARUS = shutil.which('iverilog') and shutil.which('vvp')


def interleavings(first, second):
    """Every order of two sequences that keeps the order inside each."""
    for order in set(permutations([0] * len(first) + [1] * len(second))):
        steps, position = [], [0, 0]
        for hart in order:
            steps.append((hart, (first, second)[hart][position[hart]]))
            position[hart] += 1
        yield steps


class AtomicTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-riscv-atomic'
    GOALS = 40

    def test_unprotected_increment_loses_an_update_and_amoadd_does_not(self):
        # Counted here without the explorer: load and store as two steps, AMOADD as one.
        plain = set()
        for steps in interleavings(['load', 'store'], ['load', 'store']):
            counter, read = 0, [0, 0]
            for hart, operation in steps:
                if operation == 'load':
                    read[hart] = counter
                else:
                    counter = read[hart] + 1
            plain.add(counter)
        self.assertEqual(plain, {1, 2})
        self.assertEqual({o[0] for o in L.explore('plain')['witnesses']}, plain)
        self.assertEqual({o[0] for o in L.explore('amoadd')['witnesses']}, {2})

    def test_lrsc_programs_never_lose_an_update_and_one_hart_at_most_fails(self):
        for name in ('spinlock', 'lrsc'):
            outcomes = set(L.explore(name)['witnesses'])
            self.assertEqual(outcomes, {(2, False, False, False), (2, True, False, False), (2, False, True, False)}, name)

    def test_only_the_lock_built_from_load_and_store_lets_both_harts_in(self):
        self.assertEqual(L.explore('spinlock')['overlapping_states'], 0)
        broken = L.explore('taslock')
        self.assertGreater(broken['overlapping_states'], 0)
        self.assertIn((1, False, False, True), broken['witnesses'])  # the lost update needs the overlap
        self.assertNotIn((1, False, False, False), broken['witnesses'])
        self.assertEqual({name: L.explore(name)['states'] for name in L.PROGRAMS},
                         dict(spinlock=62, lrsc=17, amoadd=5, plain=13, taslock=64))

    def test_sc_result_follows_from_the_history_of_operations(self):
        for grain, neighbour in ((0, True), (1, False)):
            p = P.Plan(grain)
            p.cycle(rst=0)
            self.assertEqual(p.transfer(0, P.SC, 2, 1), 1)                      # never reserved
            p.transfer(0, P.LR, 2); p.transfer(1, P.STORE, 3, 5)
            self.assertEqual(p.transfer(0, P.SC, 2, 7), int(not neighbour))     # the word next to it
            p.transfer(0, P.LR, 2); p.transfer(1, P.LOAD, 2); p.transfer(1, P.LR, 2)
            self.assertEqual(p.transfer(0, P.SC, 2, 8), 0)                      # reads do not disturb
            self.assertEqual(p.transfer(1, P.SC, 2, 9), 1)                      # the SC of hart 0 did
            self.assertEqual(p.memory[2], 8)

    def test_amo_functions_on_words_whose_order_depends_on_the_sign(self):
        big, one = 0x80000000, 1
        self.assertEqual([P.amo_result(fn, big, one) for fn in (P.MIN, P.MAX, P.MINU, P.MAXU)], [big, one, one, big])
        self.assertEqual(P.amo_result(P.ADD, 0xffffffff, 2), 1)
        self.assertEqual([P.amo_result(fn, 0b1100, 0b1010) for fn in (P.SWAP, P.XOR, P.AND, P.OR)],
                         [0b1010, 0b0110, 0b1000, 0b1110])
        with self.assertRaises(ValueError):
            P.amo_result(9, 0, 0)

    def test_scenario_must_state_the_sc_result_it_gets(self):
        p = P.Plan(0)
        p.cycle(rst=0)
        with self.assertRaises(ValueError):
            p.sc(0, 0, 1, True)
        with self.assertRaises(ValueError):  # a hart whose response is still waiting
            p.cycle(valid=1, hart=0, op=P.LOAD, ready=0) and p.transfer(0, P.LOAD)

    @unittest.skipUnless(ICARUS, 'Icarus required')
    def test_fixed_scenario_alone_reaches_every_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example(self.EXAMPLE, out, '--iterations', '1')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name, item in read_json(out / 'coverage.json').items():
                self.assertEqual(item['hit'], self.GOALS)
                self.assertTrue(all(f'{name}-boundaries' in cases for cases in item['hits'].values()), name)

    @unittest.skipUnless(ICARUS, 'Icarus required')
    def test_checks_that_no_mutant_needs_still_work(self):
        rows = P.vectors(17, 0, 0, True)[0]
        edits = {
            'ATOM_DATA': [("LOAD: begin result[hart] <= memory[address];", "LOAD: begin result[hart] <= ~memory[address];")],
            'ATOM_FLOW': [("assign req_ready = rst_n && legal && !resp_valid[hart]", "assign req_ready = rst_n && legal")],
            'ATOM_X': [("for (i = 0; i < 4; i = i + 1) memory[i] <= 32'd0;", "")],
            # The ISA lets an SC fail at any time; this bench expects the SC of this design to succeed.
            'ATOM_SC': [("wire sc_ok = reserved[hart] &&", "wire sc_ok = 1'b0 && reserved[hart] &&")],
        }
        for label, changes in edits.items():
            with self.subTest(label=label):
                result = simulate_vectors(P, rows, replacements={'atomic_mem.sv': changes})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'CHECK_FAIL {label}\n', result.stdout)

    @unittest.skipUnless(ICARUS, 'Icarus required')
    def test_litmus_checks_read_the_design_and_not_the_plan(self):
        # Legal operations, consistent expectations, but a result the program must not have.
        lost = P.Plan(0)
        lost.cycle(rst=0, tag=L.IDS['amoadd'])
        lost.transfer(0, P.LOAD, L.COUNTER); lost.transfer(1, P.LOAD, L.COUNTER)
        lost.transfer(0, P.STORE, L.COUNTER, 1); lost.transfer(1, P.STORE, L.COUNTER, 1)
        lost.cycle(tag=8 + L.IDS['amoadd'])
        two = P.Plan(0)
        two.cycle(rst=0, tag=L.IDS['spinlock'])
        for hart in (0, 1):
            two.transfer(hart, P.LR, L.LOCK); two.sc(hart, L.LOCK, 1, True)
        two.cycle()
        for plan, label in ((lost, 'ATOM_LITMUS'), (two, 'ATOM_MUTEX')):
            result = simulate_vectors(P, plan.rows)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f'CHECK_FAIL {label}\n', result.stdout)

    @unittest.skipUnless(ICARUS, 'Icarus required')
    def test_the_neighbouring_word_matters_only_in_the_wider_reservation_set(self):
        rows = P.vectors(17, 0, 1, True)[0]
        self.assertEqual(simulate_vectors(P, rows, {'GRAIN': 1}).returncode, 0)
        wrong = simulate_vectors(P, rows, {'GRAIN': 0})
        self.assertIn('CHECK_FAIL ATOM_SC\n', wrong.stdout)


if __name__ == '__main__':
    unittest.main()
