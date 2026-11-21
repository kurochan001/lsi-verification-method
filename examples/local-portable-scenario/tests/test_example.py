import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors
P = load_example('local-portable-scenario')
M = P.MODEL
HERE = Path(__file__).resolve().parents[1]
W = M.region_word
F = tuple(range(0x100, 0x110))


def args(**kw):
    values = dict(seed=17, profile='smoke', iterations=P.ITERATIONS['smoke'], demo_bug=0)
    values.update(kw)
    return SimpleNamespace(**values)


def tools():
    """Icarus is required; its absence fails the test instead of skipping it."""
    missing = [t for t in ('iverilog', 'vvp') if not shutil.which(t)]
    if missing:
        raise AssertionError('missing tools: ' + ', '.join(missing))


def simulate(rows, **parameters):
    tools()
    return simulate_vectors(P, rows, parameters or dict(WAIT=0))


def label(run):
    found = re.findall(r'^CHECK_FAIL (\w+)$', run.stdout, re.M)
    return found[0] if found else None


class ConstraintTests(unittest.TestCase):
    def rejected(self, actions):
        with self.assertRaises(M.Rejected) as caught:
            M.check(actions)
        return caught.exception.reason

    def test_each_rule_refuses_the_scenario_that_breaks_only_it(self):
        base = [('fill', 0, F)]
        cases = {
            'channel-busy': base + [('copy', 0, W(0), W(1), 4), ('copy', 0, W(0), W(2), 4), ('wait', 0), ('wait', 0)],
            'wait-idle': base + [('wait', 1)],
            'unwaited': base + [('copy', 1, W(0), W(1), 4)],
            'undefined-read': [('fill', 0, F), ('check', 1, 1)],
            'same-region': base + [('copy', 0, W(0), W(0) + 4, 4), ('wait', 0)],
            'out-of-range': base + [('check', 8, 1)],
            'unknown-action': base + [('dance', 0)],
        }
        for reason, actions in cases.items():
            self.assertEqual(self.rejected(actions), reason, reason)

    def test_an_outstanding_copy_holds_its_regions(self):
        running = [('fill', 0, F), ('fill', 3, F), ('copy', 0, W(0), W(1), 16)]
        for intruder in [('fill', 1, F),                 # writes the destination
                         ('fill', 0, F),                 # writes the source
                         ('check', 1, 1),                # reads the destination
                         ('copy', 1, W(3), W(1), 4),     # writes the destination
                         ('copy', 1, W(3), W(0), 4),     # writes the source
                         ('copy', 1, W(1), W(2), 4)]:    # reads the destination
            self.assertEqual(self.rejected(running + [intruder, ('wait', 0), ('wait', 1)]
                                           if intruder[0] == 'copy' else running + [intruder, ('wait', 0)]),
                             'conflict', intruder)
        # Reading the source and using other regions are allowed.
        M.check(running + [('check', 0, 16), ('copy', 1, W(0), W(2), 16), ('fill', 4, F), ('wait', 0), ('wait', 1)])

    def test_the_mailbox_limit(self):
        actions = [('fill', 0, F)] + [('check', 0, 1)] * M.RECORD_WORDS
        M.check(actions)
        self.assertEqual(self.rejected(actions + [('check', 0, 1)]), 'mailbox-full')

    def test_the_refused_copies_are_exactly_the_three_rules(self):
        self.assertFalse(M.is_error(W(0), W(1), 16))
        self.assertFalse(M.is_error(W(0), 240, 16))        # ends exactly at word 255
        self.assertTrue(M.is_error(W(0), 241, 16))         # one word past the end
        self.assertTrue(M.is_error(W(0), W(1), 0))
        self.assertTrue(M.is_error(W(0), W(1), 17))
        self.assertTrue(M.is_error(250, W(1), 8))

    def test_the_generator_only_makes_legal_scenarios(self):
        reasons = set()
        for seed in range(400):
            M.check(M.generate(seed))
            try:
                M.check(M.generate(seed, ignore_locks=True))
            except M.Rejected as exc:
                reasons.add(exc.reason)
        self.assertEqual(reasons, {'conflict'})   # the deliberate generator bug is caught by the checker

    def test_a_generator_that_breaks_a_rule_stops_the_plan(self):
        original = M.generate
        broken = lambda seed: original(seed, ignore_locks=True)
        with mock.patch.object(M, 'generate', broken):
            with self.assertRaises(M.Rejected):
                for seed in range(17, 60):
                    P.make_cases(args(seed=seed, iterations=4), dict(WAIT=0))


class ModelTests(unittest.TestCase):
    def test_signature_status_and_memory_of_a_small_scenario(self):
        actions = [('fill', 0, F), ('copy', 1, W(0) + 2, W(5), 3), ('wait', 1), ('check', 5, 3),
                   ('copy', 0, W(0), 250, 8), ('wait', 0)]
        out = M.expect(actions)
        signature = 0
        for v in F[2:5]:
            signature = ((signature << 1) | (signature >> 31)) & 0xFFFFFFFF
            signature ^= v
        self.assertEqual(out['record'], [3 << 8, signature, 1 << 1])
        self.assertEqual([out['memory'][W(5) + k] for k in range(3)], list(F[2:5]))
        self.assertNotIn(250, out['memory'])   # the refused copy moved nothing
        self.assertEqual(out['copies'], 2)

    def test_the_directed_scenarios_reach_the_whole_structural_space(self):
        found = M.coverage(list(M.directed().values()))
        self.assertEqual(found['goal_share'], 1.0)
        self.assertGreater(found['pair_share'], 0.4)

    def test_the_goal_names_are_the_same_in_the_model_the_bench_and_the_catalog(self):
        bench = (HERE / 'tb/portable_tb.sv').read_text()
        table = dict((int(i), name) for i, name in re.findall(r'(\d+): goal_name = "([^"]+)";', bench))
        self.assertEqual([table[i] for i in range(len(M.STRUCTURE_GOALS))], list(M.STRUCTURE_GOALS))
        for goal in M.OBSERVED_GOALS:
            self.assertIn(goal, bench)
        catalog = json.loads((HERE / 'requirements.json').read_text())
        self.assertEqual(sorted(g for r in catalog['requirements'] for g in r['goals']), sorted(M.GOALS))

    def test_both_realizations_carry_the_same_expectations(self):
        for name, actions in M.directed().items():
            block, block_counts = M.rows(actions, M.BLOCK)
            soc, soc_counts = M.rows(actions, M.SOC)
            keep = lambda rows: [r for r in rows if r[0] in (M.EXP_REC, M.EXP_MEM, M.GOAL)]
            self.assertEqual(keep(block), keep(soc), name)
            self.assertEqual(block_counts, soc_counts)
            self.assertTrue(any(r[0] == M.ROM for r in soc) and not any(r[0] == M.ROM for r in block))
            self.assertTrue(any(r[0] == M.ACT for r in block) and not any(r[0] == M.ACT for r in soc))

    def test_the_program_writes_each_record_and_ends_with_the_marker(self):
        actions = M.directed()['basic']
        words = M.program(actions)
        stores = [w for w in words if w & 0x7F == 0x23 and (w >> 15) & 0x1F == 29]
        offsets = sorted({((w >> 25) << 5 | (w >> 7) & 0x1F) for w in stores})
        records = len(M.expect(actions)['record'])
        self.assertTrue(set(range(0, 4 * records, 4)) <= set(offsets))
        self.assertIn(4 * 31, offsets)
        self.assertEqual(words[-1], 0x00100073)

    def test_the_plan(self):
        cases = []
        for parameters in P.CONFIGS.values():
            cases += P.make_cases(args(), parameters)
        self.assertEqual(len(cases), 48)
        self.assertEqual(sum(c['category'] == 'mutation' for c in cases), 20)
        self.assertEqual(sum(c['category'] == 'diagnostic' for c in cases), 4)
        survive = {c['id'] for c in cases if c['category'] == 'diagnostic'}
        self.assertEqual(survive, {'block-survive-mutation5-contention', 'block-survive-mutation6-basic'})
        nightly = P.make_cases(args(profile='nightly', iterations=P.ITERATIONS['nightly']), dict(WAIT=0))
        self.assertEqual(len(nightly), 44)


class BenchTests(unittest.TestCase):
    """The bench's checks on real RTL, with rows that are wrong on purpose."""

    def rows(self, name='both-pending', mode=M.BLOCK, edit=None):
        rows, _ = M.rows(M.directed()[name], mode)
        return [edit(r) if edit else r for r in rows]

    def test_correct_rows_pass_in_both_realizations(self):
        for mode in (M.BLOCK, M.SOC):
            run = simulate(self.rows(mode=mode))
            self.assertEqual(run.returncode, 0, run.stdout[-1500:])
            self.assertRegex(run.stdout, r'RESULT PASS checks=\d+')

    def test_a_wrong_record_word_is_a_result_failure(self):
        for mode in (M.BLOCK, M.SOC):
            edit = lambda r: (r[0], r[1], r[2] ^ 1, r[3]) if r[0] == M.EXP_REC and r[1] == 0 else r
            run = simulate(self.rows(mode=mode, edit=edit))
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(label(run), 'SCN_RESULT')

    def test_a_wrong_memory_word_is_a_memory_failure(self):
        for mode in (M.BLOCK, M.SOC):
            first = next(r for r in self.rows(mode=mode) if r[0] == M.EXP_MEM)
            edit = lambda r: (r[0], r[1], r[2] ^ 0x80, r[3]) if r == first else r
            run = simulate(self.rows(mode=mode, edit=edit))
            self.assertEqual(label(run), 'SCN_MEMORY')

    def test_a_program_that_never_writes_the_marker_fails(self):
        rows = [r for r in self.rows(mode=M.SOC) if not (r[0] == M.ROM and r[1] > 2)]
        run = simulate(rows)
        self.assertEqual(label(run), 'SCN_RESULT')

    def test_the_watchdog_has_its_own_label(self):
        edit = lambda r: (r[0], r[1], 50, r[3]) if r[0] == M.META and r[1] == M.META_IDS['max_cycles'] else r
        for mode in (M.BLOCK, M.SOC):
            self.assertEqual(label(simulate(self.rows(mode=mode, edit=edit))), 'SCN_TIMEOUT')

    def test_a_request_that_changes_while_it_waits_is_a_port_failure(self):
        # The memory answers after two clocks; the DMA here shows another address while it waits.
        rows = self.rows('contention', M.BLOCK)
        tools()
        run = simulate_vectors(P, rows, dict(WAIT=2), replacements={'scn_dma.sv': [
            ('assign mem_addr = phase ? c_dst + {3\'d0, c_moved} : c_src + {3\'d0, c_moved};',
             'assign mem_addr = (phase ? c_dst + {3\'d0, c_moved} : c_src + {3\'d0, c_moved}) ^ {7\'d0, !mem_ready};')]})
        self.assertEqual(label(run), 'SCN_PORT')


class RunTests(unittest.TestCase):
    def test_smoke_run_and_a_missing_simulator(self):
        tools()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = run_example('local-portable-scenario', out)
            self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['planned'], summary['mutations_detected'], summary['diagnostics_pass']), (48, 20, 4))
            coverage = read_json(out / 'coverage.json')
            self.assertTrue(all(c['success'] and c['hit'] == len(M.GOALS) for c in coverage.values()))
            self.assertEqual((out / 'junit.xml').read_text().count('<testcase'), 50)
            broken = run_example('local-portable-scenario', Path(tmp) / 'broken', '--iverilog', 'no-such-iverilog')
            self.assertNotEqual(broken.returncode, 0)
            demo = run_example('local-portable-scenario', Path(tmp) / 'demo', '--demo-bug', '5')
            self.assertEqual(demo.returncode, 1)


if __name__ == '__main__':
    unittest.main()
