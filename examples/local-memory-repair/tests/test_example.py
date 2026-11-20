from itertools import combinations
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-memory-repair')
M = P.MODEL
SMALL, LARGE = P.CONFIGS['s1x1'], P.CONFIGS['s2x2']
FUSE_BENCH = '''`timescale 1ns/1ps
module fuse_tb;
    reg clk = 0, blank = 1, prog = 0; reg [3:0] d = 0; wire [3:0] q;
    fuse_bank #(.WIDTH(4)) dut(.clk(clk), .blank(blank), .prog(prog), .d(d), .q(q));
    always #5 clk = ~clk;
    initial begin
        @(negedge clk) blank = 0; prog = 1; d = 4'b0101;
        @(negedge clk) $display("Q %b", q); d = 4'b0010;
        @(negedge clk) $display("Q %b", q); d = 4'b0000;
        @(negedge clk) $display("Q %b", q); prog = 0; d = 4'b1000;
        @(negedge clk) $display("Q %b", q); $finish;
    end
endmodule
'''


def by_forced_columns(p, faults):
    """A second way to the verdict: choose rows, then every remaining faulty column is forced."""
    main = M.main_faults(p, faults)
    rows_free, cols_free = (len(spares) for spares in M.good_spares(p, faults))
    if not main:
        return M.PASS
    faulty_rows = sorted({r for r, _ in main})
    for count in range(rows_free + 1):
        for rows in combinations(faulty_rows, count):
            if len({c for r, c in main if r not in rows}) <= cols_free:
                return M.REPAIRED
    return M.UNREPAIRABLE


def label(result):
    lines = [line for line in result.stdout.splitlines() if line.startswith('CHECK_FAIL')]
    return lines[0].split()[1] if len(lines) == 1 and result.returncode else None


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-memory-repair'
    GOALS = 19

    def test_verdict_of_hand_made_patterns(self):
        self.assertEqual(M.verdict(SMALL, {}), M.PASS)
        self.assertEqual(M.verdict(SMALL, {(4, 0): 1, (0, 4): 0}), M.PASS)             # spares only
        self.assertEqual(M.verdict(SMALL, {(0, 0): 1, (1, 1): 1}), M.REPAIRED)         # one row, one column
        self.assertEqual(M.verdict(SMALL, {(0, 0): 1, (1, 1): 1, (2, 2): 1}), M.UNREPAIRABLE)
        self.assertEqual(M.verdict(SMALL, {(0, 0): 1, (1, 1): 1, (4, 3): 1}), M.UNREPAIRABLE)  # the spare row is bad
        self.assertEqual(M.verdict(LARGE, {(k, k): 1 for k in range(4)}), M.REPAIRED)
        self.assertEqual(M.verdict(LARGE, {(k, k): 1 for k in range(5)}), M.UNREPAIRABLE)
        # A fault where a spare row crosses a spare column takes both away.
        self.assertEqual(M.good_spares(LARGE, {(8, 9): 1}), ([1], [0]))

    def test_both_ways_to_the_verdict_agree(self):
        rng = random.Random(5)
        for p in (SMALL, LARGE):
            seen = set()
            for _ in range(400):
                faults = M.random_faults(p, rng)
                seen.add(M.verdict(p, faults))
                self.assertEqual(M.verdict(p, faults), by_forced_columns(p, faults), faults)
            self.assertEqual(seen, {M.PASS, M.REPAIRED, M.UNREPAIRABLE})

    def test_must_repair_rule_and_its_overflow(self):
        self.assertEqual(M.must_rows(SMALL, {(2, 0): 1, (2, 3): 1, (1, 1): 1}), [2])
        self.assertEqual(M.kind(SMALL, {(2, 0): 1, (2, 3): 1}), M.KIND_MUST)
        self.assertEqual(M.kind(SMALL, {(2, 0): 1, (2, 3): 1, (0, 1): 1, (0, 2): 1}), M.KIND_MUST_OVERFLOW)
        self.assertEqual(M.kind(LARGE, {(2, 0): 1, (2, 3): 1}), 0)        # two spare columns are enough
        self.assertEqual(M.kind(LARGE, {(2, 0): 1, (0, 9): 1}), 0)        # one spare column is left
        self.assertEqual(M.kind(LARGE, {(2, 0): 1, (0, 8): 1, (0, 9): 1}), M.KIND_MUST)  # none is left

    def test_fixed_patterns_hold_what_each_mutant_needs(self):
        for p in (SMALL, LARGE):
            patterns = dict(M.boundary_faults(p))
            verdicts = {name: M.verdict(p, faults) for name, faults in patterns.items()}
            self.assertEqual([verdicts[n] for n in ('clean', 'single', 'must-row', 'shared-columns', 'row-and-column')],
                             [M.PASS] + [M.REPAIRED] * 4)
            # Mutant 1 takes a row for each of these rows and runs out of spare rows.
            shared = M.main_faults(p, patterns['shared-columns'])
            self.assertEqual(len({r for r, _ in shared}), p['SR'] + 1)
            self.assertTrue(all(sum(r == row for r, _ in shared) == p['SC'] for row in {r for r, _ in shared}))
            # Mutant 4 swaps rows and columns: the first repaired pattern must not be symmetric.
            self.assertNotIn((2, 1), patterns['single'])
            # Mutant 6 counts a faulty spare: without that fault the pattern would be repairable.
            bad = patterns['bad-spare-row']
            self.assertEqual(verdicts['bad-spare-row'], M.UNREPAIRABLE)
            self.assertEqual(M.verdict(p, {cell: v for cell, v in bad.items() if cell[0] < p['ROWS']}), M.REPAIRED)
            self.assertEqual(M.counts(M.boundary_vectors(p)),
                             dict(steps=13, clean=2, repaired=8, unrepairable=3, retests=8, late_faults=1))

    def test_vector_rejects_cells_outside_the_array(self):
        with self.assertRaises(ValueError):
            M.row(SMALL, {(5, 0): 1})
        with self.assertRaises(ValueError):
            M.row(dict(ROWS=16, COLS=16, SR=1, SC=1), {})
        self.assertEqual(M.row(SMALL, {(0, 0): 1}, late=1)[5:7], [M.REPAIRED, M.FAILED])
        self.assertEqual(M.row(SMALL, {}, late=1)[2], 0)    # nothing to retest without a repair

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus required')
    def test_fuses_only_gain_bits(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = Path(tmp) / 'fuse_tb.sv'
            bench.write_text(FUSE_BENCH)
            subprocess.run(['iverilog', '-g2012', '-o', str(Path(tmp) / 'fuse.vvp'), str(P.HERE / 'rtl/fuse_bank.sv'), str(bench)],
                           check=True, capture_output=True, text=True, timeout=30)
            out = subprocess.run(['vvp', str(Path(tmp) / 'fuse.vvp')], capture_output=True, text=True, timeout=30).stdout
        self.assertEqual([line.split()[1] for line in out.splitlines() if line.startswith('Q ')],
                         ['0101', '0111', '0111', '0111'])

    def test_every_pattern_of_up_to_three_faults_in_the_small_array(self):
        """The allocation of the RTL is complete here: it repairs whatever the search can repair."""
        cells = [(r, c) for r in range(4) for c in range(4)]
        rows = [M.row(SMALL, {cell: 1 for cell in chosen}) for count in range(4) for chosen in combinations(cells, count)]
        self.assertEqual(len(rows), 1 + 16 + 120 + 560)
        self.assertEqual(M.counts(rows)['unrepairable'], 96)    # three faults with no two on one line
        result = simulate_vectors(P, rows, SMALL)
        self.assertEqual(result.returncode, 0, result.stdout[-600:])
        self.assertIn(f'RESULT PASS checks={len(rows)}', result.stdout)

    def test_bench_does_not_follow_a_wrong_expectation(self):
        optimistic = M.row(SMALL, {(0, 0): 1, (1, 1): 1, (2, 2): 1})
        optimistic[5] = M.REPAIRED
        self.assertEqual(label(simulate_vectors(P, [optimistic], SMALL)), 'REPAIR_VERDICT')
        pessimistic = M.row(SMALL, {(0, 0): 1})
        pessimistic[5] = M.UNREPAIRABLE
        self.assertEqual(label(simulate_vectors(P, [pessimistic], SMALL)), 'REPAIR_UNREPAIRABLE')
        late = M.row(SMALL, {(0, 0): 1}, late=1)
        late[6] = M.PASS
        self.assertEqual(label(simulate_vectors(P, [late], SMALL)), 'REPAIR_RETEST')

    def test_checkers_that_no_mutant_of_the_plan_reaches(self):
        # A faulty spare row taken for the repair, although the other one is free.
        vector = [M.row(LARGE, {(8, 1): 1, **{(2, c): 1 for c in range(3)}})]
        edit = {'mem_repair.sv': [("for (a = 0; a < SR; a = a + 1)\n            if (!row_spare_bad[a]) begin\n                found",
                                   "for (a = 0; a < SR; a = a + 1)\n            if (1'b1) begin\n                found")]}
        self.assertEqual(label(simulate_vectors(P, vector, LARGE, edit)), 'REPAIR_SPARE')
        # Fuses that lose their bits when nothing is being programmed.
        edit = {'fuse_bank.sv': [('else if (prog) q <= q | d;', 'else q <= prog ? (q | d) : {WIDTH{1\'b0}};')]}
        self.assertEqual(label(simulate_vectors(P, [M.row(SMALL, {(0, 0): 1})], SMALL, edit)), 'REPAIR_FUSE')
        # A second test, and a second programming, without the reset in between.
        edit = {'mem_repair.sv': [('if (start && !spent) begin', 'if (start) begin')]}
        self.assertEqual(label(simulate_vectors(P, [M.row(SMALL, {(0, 0): 1})], SMALL, edit)), 'REPAIR_REBOOT')
        # A March that leaves out its last element.
        edit = {'mem_repair.sv': [("else if (phase == 3'd5) state", "else if (phase == 3'd4) state")]}
        self.assertEqual(label(simulate_vectors(P, [M.row(SMALL, {})], SMALL, edit)), 'REPAIR_COUNT')


if __name__ == '__main__':
    unittest.main()
