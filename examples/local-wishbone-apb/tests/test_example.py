import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example
P = load_example('local-wishbone-apb')
HERE = Path(__file__).resolve().parents[1]
ACK, ERR, RDAT, PSEL, PENABLE, PWRITE, PADDR, PWDATA, PSTRB = range(11, 20)


def rows(build):
    plan = P.Plan()
    build(plan)
    return plan


class ModelTests(unittest.TestCase):
    def test_a_transfer_takes_one_request_clock_the_apb_clocks_and_one_answer(self):
        for wait in range(5):
            plan = rows(lambda p: p.transfer(P.request(1, 0x10, 0x55, 9), wait=wait))
            self.assertEqual(len(plan.rows), wait + 4)
            self.assertEqual([r[PSEL] for r in plan.rows], [0] + [1] * (wait + 2) + [0])
            self.assertEqual([r[PENABLE] for r in plan.rows], [0, 0] + [1] * (wait + 1) + [0])
            self.assertEqual([r[ACK] for r in plan.rows], [0] * (wait + 3) + [1])
            self.assertTrue(all(r[PADDR:] == [0x10, 0x55, 9] for r in plan.rows[1:-1]))
            self.assertEqual(plan.completed, 1)

    def test_reads_drive_no_strobe_and_return_only_the_selected_lanes(self):
        plan = rows(lambda p: p.transfer(P.request(0, 4, 0xffffffff, 5), rdata=0x11223344))
        self.assertTrue(all(r[PWDATA] == 0 and r[PSTRB] == 0 for r in plan.rows))
        self.assertEqual(plan.rows[-1][RDAT], 0x00220044)
        self.assertEqual([P.select(0x11223344, s) for s in (0, 1, 8, 15)], [0, 0x44, 0x11000000, 0x11223344])

    def test_an_error_replaces_the_acknowledge_and_hides_the_data(self):
        plan = rows(lambda p: p.transfer(P.request(0, 4), wait=2, err=1, rdata=0xffffffff, noise=1))
        self.assertEqual(plan.rows[-1][ACK:RDAT + 1], [0, 1, 0])
        self.assertEqual([r[8] for r in plan.rows], [0, 0, 1, 1, 1, 0])  # PSLVERR is noise in the two wait clocks

    def test_an_abandoned_cycle_finishes_on_apb_and_is_never_answered(self):
        for position in (('setup', 0), ('wait', 0), ('wait', 1), ('complete', 0), ('response', 0)):
            plan = rows(lambda p: p.transfer(P.request(1, 8, 1), wait=2, leave=position))
            self.assertEqual(sum(r[PSEL] for r in plan.rows), 4, position)
            self.assertEqual(sum(r[ACK] + r[ERR] for r in plan.rows), 0, position)
            self.assertEqual(plan.completed, 0)
            # Only a master that leaves in the answer clock itself still gets that clock.
            self.assertEqual(len(plan.rows), 6 if position[0] == 'response' else 5, position)

    def test_a_waiting_request_is_taken_only_after_the_abandoned_transfer(self):
        follower = P.request(0, 0x24, sel=3)
        plan = rows(lambda p: p.transfer(P.request(1, 0x20, 7), wait=2, leave=('setup', 0), pending=follower))
        first = [r for r in plan.rows if r[PSEL] and r[PADDR] == 0x20]
        second = [r for r in plan.rows if r[PSEL] and r[PADDR] == 0x24]
        self.assertEqual((len(first), len(second)), (4, 3))
        self.assertEqual([r[4] for r in first], [0, 0x24, 0x24, 0x24])  # the follower is already on the pins
        self.assertEqual(plan.rows.index(second[0]), plan.rows.index(first[-1]) + 2)
        self.assertEqual(sum(r[ACK] for r in plan.rows), 1)
        self.assertEqual(plan.rows[-1][RDAT], P.select(0x0badcafe, 3))

    def test_reset_ends_the_transfer_in_the_clock_it_is_applied(self):
        for position, length, selected in ((('setup', 0), 2, 1), (('wait', 1), 4, 1), (('complete', 0), 5, 1), (('response', 0), 6, 0)):
            plan = rows(lambda p: p.transfer(P.request(1, 8, 1), wait=2, reset=position))
            self.assertEqual(len(plan.rows), length, position)
            self.assertEqual(plan.rows[-1][:3] + [plan.rows[-1][PSEL]], [0, 0, 0, selected], position)

    def test_an_idle_clock_cannot_carry_a_request(self):
        with self.assertRaises(ValueError):
            P.Plan().idle(master=P.request(0, 0))


class PlanTests(unittest.TestCase):
    def args(self, **changes):
        return SimpleNamespace(**{**dict(profile='smoke', seed=17, iterations=3, demo_bug=0), **changes})

    def test_the_plan_names_every_case_and_label(self):
        cases = P.make_cases(self.args(), P.CONFIGS['aw16'])
        self.assertEqual(len(cases), 2 + P.MUTANTS + len(P.MONITOR_LABELS) + len(P.MONITOR_MISSES))
        self.assertEqual(len(P.make_cases(self.args(profile='nightly'), P.CONFIGS['aw16'])), len(cases) + 2)
        self.assertEqual(sorted(set(P.MONITOR_LABELS) | set(P.MONITOR_MISSES)), list(range(1, P.MUTANTS + 1)))
        self.assertFalse(set(P.MONITOR_LABELS) & set(P.MONITOR_MISSES))
        text = (HERE / 'tb/wb_apb_tb.sv').read_text()
        self.assertEqual(set(P.LABELS.values()) | set(P.MONITOR_LABELS.values()) | {'WBA_WB_PROTOCOL', 'WBA_UNKNOWN'},
                         set(re.findall(r'fail\("(\w+)"\)', text)))
        blind = next(c for c in cases if c['id'] == 'monitor-misses-mutation1')
        self.assertTrue(all(row[10] == 0 for row in blind['vectors']))
        self.assertTrue(all(row[10] == 1 for row in cases[0]['vectors']))

    def test_seed_reproduction(self):
        first = P.make_cases(self.args(), P.CONFIGS['aw8'])
        self.assertEqual(first, P.make_cases(self.args(), P.CONFIGS['aw8']))
        self.assertNotEqual(first[1], P.make_cases(self.args(seed=18), P.CONFIGS['aw8'])[1])
        self.assertEqual(first[0], P.make_cases(self.args(seed=18), P.CONFIGS['aw8'])[0])

    def test_addresses_stay_inside_the_configured_width(self):
        for name, parameters in P.CONFIGS.items():
            for case in P.make_cases(self.args(iterations=40), parameters)[:2]:
                self.assertTrue(all(row[4] < 1 << parameters['AW'] and row[17] < 1 << parameters['AW'] for row in case['vectors']), name)
                self.assertTrue(any(row[17] == (1 << parameters['AW']) - 1 for row in case['vectors']), name)

    def test_requirements_and_bench_name_the_same_goals(self):
        catalog = json.loads((HERE / 'requirements.json').read_text(encoding='utf-8'))
        goals = [g for r in catalog['requirements'] for g in r['goals']]
        self.assertEqual((len(catalog['requirements']), len(goals), len(set(goals))), (6, 26, 26))
        self.assertEqual(set(goals), set(re.findall(r'COVER (\S+?)"', (HERE / 'tb/wb_apb_tb.sv').read_text())))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog is required')

    def test_real_rtl_all_configurations_mutants_and_monitor_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-wishbone-apb', out, '--iterations', '3')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['success'], summary['planned'], summary['results']), (True, 40, 40))
            self.assertEqual((summary['functional_pass'], summary['mutations_detected'], summary['diagnostics_pass']), (4, 26, 10))
            coverage = read_json(out / 'coverage.json')
            for name in P.CONFIGS:
                self.assertEqual((coverage[name]['hit'], coverage[name]['required']), (26, 26))
                # Every goal is reached by the fixed scenario alone.
                self.assertTrue(all(any(i.endswith('-boundaries') for i in ids) for ids in coverage[name]['hits'].values()))
                self.assertEqual(read_json(out / f'{name}-monitor-misses-mutation8/result.json')['status'], 'pass')
                self.assertIn('WBA_APB_PROTOCOL', (out / f'{name}-monitor-detects-mutation7/simulation.log').read_text())
            cases = list(ET.parse(out / 'junit.xml').getroot().iter('testcase'))
            self.assertEqual(len(cases), 42)
            self.assertFalse([c for c in cases if list(c)])
            manifest = read_json(out / 'manifest.json')
            self.assertEqual(sorted(manifest['configurations']), sorted(P.CONFIGS))

    def test_demo_faults_make_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run_example('local-wishbone-apb', out, '--configuration', 'aw8', '--iterations', '2', '--demo-bug', str(fault))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(read_json(out / 'aw8-boundaries/result.json')['status'], 'fail')


if __name__ == '__main__':
    unittest.main()
