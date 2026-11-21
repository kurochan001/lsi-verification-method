import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import assert_evidence, load_example, read_json, run_example

P = load_example('local-synth-testbench')
M = P.M
GOALS = 14


def tools_present():
    return all(shutil.which(name) for name in ('iverilog', 'vvp', 'yowasp-yosys'))


class ModelTests(unittest.TestCase):
    def test_the_lfsr_visits_every_nonzero_state_once(self):
        states = M.stimuli(0xace1, 65535)
        self.assertEqual(len(set(states[:65535])), 65535)
        self.assertNotIn(0, states)
        self.assertEqual(states[65535], 0xace1)

    def test_the_alu_against_plain_integer_arithmetic(self):
        for a in range(0, 256, 3):
            for b in range(0, 256, 5):
                self.assertEqual(M.alu(a, b, 0), a + b)
                self.assertEqual(M.alu(a, b, 1), ((a - b) & 0xff) | ((a >= b) << 8))
                self.assertEqual(M.alu(a, b, 2), a & b)
                self.assertEqual(M.alu(a, b, 3), a ^ b)

    def test_every_operation_and_a_carry_occur_in_each_configuration(self):
        for name, c in P.CONFIGS.items():
            states = M.stimuli(c['SEED'], c['PATTERNS'])[:c['PATTERNS']]
            self.assertEqual({M.operands(s)[2] for s in states}, {0, 1, 2, 3}, name)
            self.assertTrue(any(M.response_of(s) >> 8 for s in states), name)

    def test_the_golden_signature_is_the_fold_of_the_responses(self):
        for c in P.CONFIGS.values():
            responses = [M.response_of(s) for s in M.stimuli(c['SEED'], c['PATTERNS'])[:c['PATTERNS']]]
            signature = 0
            for value in responses:        # written out again: shift, feedback, add
                signature = ((signature << 1) & 0xffff) ^ (0x1021 if signature & 0x8000 else 0) ^ value
            self.assertEqual(signature, c['GOLDEN'])

    def test_one_wrong_response_never_passes(self):
        """The MISR step is invertible, so a single difference can never return to zero."""
        for c in P.CONFIGS.values():
            p = c['PATTERNS']
            clean = [M.response_of(s) for s in M.stimuli(c['SEED'], p)[:p]]
            for k in range(p):
                for fault in range(1, 1 << 9):
                    wrong = list(clean)
                    wrong[k] ^= fault
                    if fault in (1, 2, 0x100) or k in (0, p - 1):
                        self.assertNotEqual(M.signature_of(wrong), c['GOLDEN'])

    def test_the_cancelling_pair_passes_and_a_different_pair_fails(self):
        for c in P.CONFIGS.values():
            p = c['PATTERNS']
            clean = [M.response_of(s) for s in M.stimuli(c['SEED'], p)[:p]]
            faults = P.alias_faults(p)
            wrong = list(clean)
            for k, f in faults.items():
                wrong[k] ^= f
            self.assertEqual(M.signature_of(wrong), c['GOLDEN'])
            k = min(faults)
            wrong[k + 1] ^= 1                   # one more bit: the pair no longer cancels
            self.assertNotEqual(M.signature_of(wrong), c['GOLDEN'])
        with self.assertRaises(ValueError):
            M.cancelling_fault(0x1ff)           # needs a 10th bit: no single response can cancel it

    def test_aliasing_fraction_of_a_small_misr_is_the_counting_formula(self):
        """Every nonzero error sequence, counted: with n state bits and L*w input bits in total,
        2**(L*w - n) - 1 of the 2**(L*w) - 1 sequences alias. That is close to 2**-n."""
        def fold4(state, value):
            return ((state << 1) & 0xf) ^ (0x3 if state & 0x8 else 0) ^ value
        for width, length in ((1, 8), (2, 6), (3, 4)):
            total = width * length
            aliased = 0
            for code in range(1, 1 << total):
                state = 0
                for i in range(length):
                    state = fold4(state, (code >> (i * width)) & ((1 << width) - 1))
                aliased += state == 0
            self.assertEqual(aliased, (1 << (total - 4)) - 1, (width, length))

    def test_counts_and_flip_flops_follow_the_rows_and_the_widths(self):
        rows = P.scenario_rows(P.CONFIGS['rtl-p64'])
        self.assertEqual(P.counts(rows), dict(runs=6, passes=4))   # 2 full, the chip clean run, 2 with wrong responses, 1 full
        self.assertEqual(P.flip_flops(64), 16 + 16 + 9 + 7 + 4)
        self.assertEqual(P.flip_flops(40), 51)

    def test_the_structure_check_rejects_a_netlist_that_lost_registers(self):
        good = 'Number of cells: 405\n       51   $_DFF_P_\n       12   $_ANDNOT_\n'
        self.assertEqual(P.structure(good, 40), (51, True))
        self.assertEqual(P.structure(good.replace('51   $_DFF_P_', '35   $_DFF_P_'), 40), (35, False))
        self.assertEqual(P.structure('no statistics here', 40), (0, False))

    def test_the_plan_reaches_every_goal_without_random_runs(self):
        catalog = read_json(Path(P.__file__).parent / 'requirements.json')
        goals = {g for r in catalog['requirements'] for g in r['goals']}
        self.assertEqual(len(goals), GOALS)


class RealRunTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(tools_present(), 'Icarus and yowasp-yosys are required for these tests')

    def test_smoke_evidence_and_a_planted_bug_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = run_example('local-synth-testbench', out)
            self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
            assert_evidence(self, out, list(P.CONFIGS), GOALS, 24, diagnostics=2, mutants=9)
            builds = read_json(out / 'builds.json')
            netlists = [b['preparation'] for k, b in builds.items() if k.startswith('netlist')]
            self.assertEqual(len(netlists), 8)
            self.assertTrue(all(b['flip_flops'] == b['expected_flip_flops'] == 51 for b in netlists))
            for case in ('rtl-p64-scenario', 'netlist-p40-scenario'):
                self.assertEqual(read_json(out / case / 'result.json')['counts'], P.counts(
                    P.scenario_rows(P.CONFIGS[case.rsplit('-scenario', 1)[0]])))
            broken = run_example('local-synth-testbench', Path(tmp) / 'broken', '--configuration', 'rtl-p64', '--demo-bug', '3')
            self.assertEqual(broken.returncode, 1)

    def test_seed_reproduces_the_random_rows(self):
        c = P.CONFIGS['rtl-p64']
        self.assertEqual(P.random_rows(5, 4, c), P.random_rows(5, 4, c))
        self.assertNotEqual(P.random_rows(5, 4, c), P.random_rows(6, 4, c))

    def test_a_synthesis_that_drops_the_signature_is_refused(self):
        """Cut the observation of the signature: Yosys removes the MISR and the build must fail."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'example'
            shutil.copytree(Path(P.__file__).parent, root, ignore=shutil.ignore_patterns('__pycache__'))
            harness = root / 'rtl/selftest_harness.sv'
            text = harness.read_text()
            text = text.replace('output reg [15:0] signature\n', 'output wire [15:0] signature\n')
            text = text.replace('    reg [CW-1:0] issued;\n', '    reg [CW-1:0] issued;\n    reg [15:0] misr;\n    assign signature = 16\'d0;\n')
            text = text.replace('signature <= ', 'misr <= ').replace('{signature[14:0], 1\'b0} ^ (signature[15]', '{misr[14:0], 1\'b0} ^ (misr[15]')
            text = text.replace("(MUTATION == 7 ? signature : next_signature) == GOLDEN_BITS", "1'b1")
            harness.write_text(text)
            spec = importlib.util.spec_from_file_location('copy_run', root / 'run.py')
            copy = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(copy)
            runner_spec = importlib.util.spec_from_file_location('local_runner', Path(P.__file__).parent.parent / 'local-common/runner.py')
            runner = importlib.util.module_from_spec(runner_spec)
            sys.modules['local_runner'] = runner
            runner_spec.loader.exec_module(runner)
            args = type('A', (), dict(yosys='yowasp-yosys', cell_library=None, timeout=60))()
            sources, prepared = copy.build_sources(args, 'netlist-p40', copy.CONFIGS['netlist-p40'], 0, Path(tmp) / 'build')
            self.assertIn('synthesized structure lost', prepared['error'] or '')
            self.assertLess(prepared['flip_flops'], prepared['expected_flip_flops'])


if __name__ == '__main__':
    unittest.main()
