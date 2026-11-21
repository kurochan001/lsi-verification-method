from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-clock-gating')
M = P.MODEL
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
SIGNAL = M.SIGNALS


def first(rows, signal, start=0):
    return next(i for i, row in enumerate(rows) if i >= start and row[1] == SIGNAL[signal])


def labels(result):
    return [line.split()[1] for line in result.stdout.splitlines() if line.startswith('CHECK_FAIL ')]


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-clock-gating'
    GOALS = 13

    def test_fixed_scenario_alone_reaches_every_goal(self):
        if not ICARUS:
            self.skipTest('Icarus required')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example(self.EXAMPLE, out, '--iterations', '1')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in P.CONFIGS:
                record = read_json(out / f'{name}-boundaries/result.json')
                self.assertEqual(len(record['credited_coverage']), self.GOALS, name)
                edges = (out / f'{name}-boundaries/wave.vcd.edges.csv').read_text().splitlines()
                self.assertEqual(edges[0], 'time_ps,signal,value')
                self.assertGreater(len(edges), 100)

    def test_each_expected_count_is_really_compared(self):
        if not ICARUS:
            self.skipTest('Icarus required')
        parameters = P.CONFIGS['a10-b14-div3']
        for signal, label, change in (('CHECK_GATE', 'CG_EDGES', 1), ('WINDOW_CLOSE', 'CS_EDGES', 1),
                                      ('CHECK_DIV', 'DIV_EDGES', 1), ('CHECK_ACTIVE', 'CS_ACTIVE', 1)):
            with self.subTest(label=label):
                rows, _ = M.vectors(parameters, 17, 0)
                rows[first(rows, signal)][2] += change
                result = simulate_vectors(P, rows, parameters)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(labels(result), [label], result.stdout)

    def test_clean_run_reports_the_counts_of_the_model(self):
        if not ICARUS:
            self.skipTest('Icarus required')
        for parameters in P.CONFIGS.values():
            rows, counts = M.vectors(parameters, 5, 12)
            result = simulate_vectors(P, rows, parameters)
            self.assertEqual(result.returncode, 0, result.stdout)
            reported = dict(line.split()[1].split('=') for line in result.stdout.splitlines() if line.startswith('COUNT '))
            self.assertEqual({name: int(value) for name, value in reported.items()}, counts)


class ModelTests(unittest.TestCase):
    PARAMETERS = dict(PERIOD_A=10000, PERIOD_B=14000, DIV=3)

    def test_inputs_never_change_on_a_clock_edge(self):
        for parameters in P.CONFIGS.values():
            for seed in (1, 2, 3):
                rows, counts = M.vectors(parameters, seed, 60)
                time = 0
                for delay, signal, _ in rows:
                    time += delay
                    if signal in M.INPUTS:
                        self.assertNotEqual(time % M.GRID, 0)
                self.assertEqual(counts['steps'], len(rows))
        with self.assertRaises(ValueError):
            M.Scenario(self.PARAMETERS).add(40000, 'EN', 1)
        with self.assertRaises(ValueError):
            M.Scenario(dict(self.PARAMETERS, DIV=4))

    def test_gate_passes_a_pulse_only_if_enabled_at_its_rising_edge(self):
        s = M.Scenario(self.PARAMETERS)
        s.set_enable(44900, 1)    # 100 ps before the rising edge at 45000
        s.set_enable(55100, 0)    # 100 ps after the rising edge at 55000
        self.assertEqual([s.gate_expected(t) for t in (44999, 45000, 54999, 55000, 99999)], [0, 1, 1, 2, 2])
        t = M.Scenario(self.PARAMETERS)
        t.set_enable(45100, 1)    # just too late for the pulse at 45000
        t.set_enable(54900, 0)
        self.assertEqual(t.gate_expected(99999), 0)

    def test_stoppable_clock_keeps_its_level_and_resumes_on_its_grid(self):
        clock = M.StoppableClock(5000)
        self.assertEqual(clock.rises(0, 30000), 3)                 # 5000, 15000, 25000
        clock.set_running(16300, 0)                                # stops high
        clock.set_running(41300, 1)
        self.assertEqual((clock.level(40000), clock.rises(16300, 41300)), (1, 0))
        self.assertEqual(clock.edges(55000)[-3:], [(45000, 0), (50000, 1), (55000, 0)])
        self.assertEqual(clock.next_rise(41300), 50000)
        self.assertEqual(M.free_rises(5000, 0, 30000), 3)
        self.assertEqual(M.free_rises(5000, 5000, 15000), 1)

    def test_fixed_switch_is_placed_where_the_two_mutants_fail(self):
        for parameters in P.CONFIGS.values():
            s = M.Scenario(parameters)
            s.window('a')
            select = s.glitch_time()
            a, b = s.clock['a'], s.clock['b']
            rise = select - 1500
            self.assertIn((rise, 1), a.edges(rise))
            # A plain multiplexer: the output is high for 1500 ps and then follows the low clock b.
            self.assertEqual((a.level(select), b.level(select)), (1, 0))
            self.assertLess(1500, min(s.half.values()))
            # Without break-before-make, b is enabled before a is released.
            self.assertLess(b.next_rise(select) + s.half['b'], a.next_rise(select) + s.half['a'])

    def test_divider_rises_on_the_first_edge_and_then_every_div_edges(self):
        for div in (3, 5):
            s = M.Scenario(dict(self.PARAMETERS, DIV=div))
            release = s.divider_release
            first_rise = next(t for t in range(5000, 10**6, 10000) if t > release)
            self.assertEqual(s.divider_expected(first_rise - 1), 0)
            self.assertEqual(s.divider_expected(first_rise), 1)
            self.assertEqual(s.divider_expected(first_rise + div * 10000 - 1), 1)
            self.assertEqual(s.divider_expected(first_rise + div * 10000), 2)

    def test_fixed_scenario_has_what_every_goal_needs(self):
        rows, counts = M.vectors(self.PARAMETERS, 17, 0)
        signals = [row[1] for row in rows]
        # start, two recoveries, and one reset released with clk_b still selected
        self.assertEqual(signals.count(SIGNAL['SW_RST']), 7)
        release = [i for i, row in enumerate(rows) if row[1] == SIGNAL['CHECK_RELEASE']]
        self.assertEqual(len(release), 1)
        # The check follows the release directly, and neither select nor a clock stop is in between.
        self.assertEqual(rows[release[0] - 1][1:], [SIGNAL['SW_RST'], 1])
        self.assertEqual([row[2] for row in rows[:release[0]] if row[1] == SIGNAL['SEL']][-1], 1)
        self.assertEqual(sum(row[1] == SIGNAL['CHECK_ACTIVE'] and row[2] == 0 for row in rows), 2)
        self.assertEqual(signals.count(SIGNAL['DIV_RST']), 3)
        self.assertEqual(counts['switch_windows'], signals.count(SIGNAL['WINDOW_CLOSE']))
        self.assertEqual((rows[-2][1], rows[-1][1]), (SIGNAL['CHECK_GATE'], SIGNAL['CHECK_DIV']))


if __name__ == '__main__':
    unittest.main()
