import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load('fault_campaign_run', HERE / 'run.py')
C, M = R.C, R.M
TOOLS = {name: shutil.which(name) for name in ('iverilog', 'vvp', 'yowasp-yosys')}


def temporary():
    # The YoWASP tools replace /tmp inside their sandbox; run below /tmp on every platform so that
    # the relative-path handling of the runner is exercised the way Linux exercises it.
    return tempfile.TemporaryDirectory(dir='/tmp' if Path('/tmp').is_dir() else None)


def tiny_netlist():
    """Two flip-flops: `a` drives the output `y` through an AND, `b` drives only the output `z`."""
    return {'modules': {'t': {
        'ports': {'clk': {'direction': 'input', 'bits': [2]}, 'x': {'direction': 'input', 'bits': [3]},
                  'y': {'direction': 'output', 'bits': [6]}, 'z': {'direction': 'output', 'bits': [5]}},
        'cells': {
            'fa': {'type': '$dff', 'port_directions': {'CLK': 'input', 'D': 'input', 'Q': 'output'},
                   'connections': {'CLK': [2], 'D': [3], 'Q': [4]}},
            'fb': {'type': '$dff', 'port_directions': {'CLK': 'input', 'D': 'input', 'Q': 'output'},
                   'connections': {'CLK': [2], 'D': [3], 'Q': [5]}},
            'g': {'type': '$and', 'port_directions': {'A': 'input', 'B': 'input', 'Y': 'output'},
                  'connections': {'A': [4], 'B': ['1'], 'Y': [6]}}},
        'netnames': {'a': {'bits': [4]}, 'b': {'bits': [5]}, 'x': {'bits': [3]}, 'y': {'bits': [6]}, 'z': {'bits': [5]},
                     'clk': {'bits': [2]}, '$auto': {'bits': [6], 'hide_name': 1}}}}}


class Classification(unittest.TestCase):
    def test_known_answers_pass_and_every_classifier_bug_is_caught(self):
        self.assertEqual(R.known_answers(), (True, []))
        caught = {bug: R.known_answers(bug)[1] for bug in (1, 2, 3, 5)}
        self.assertEqual(caught, {1: ['stall', 'cap-with-alarm'], 2: ['late-alarm'], 3: ['late-alarm', 'transient', 'missing-alarm'],
                                  5: ['missing-alarm']})
        self.assertTrue(R.known_answers(4)[0])   # bug 4 is in the accounting, not in the classifier

    def test_timeout_comes_first_even_with_an_alarm(self):
        g = R.G
        self.assertEqual(C.classify(g, [R.row(1, 1), R.row(2, 1, 1)], 'cap'), 'timeout')
        self.assertEqual(C.classify(g, [R.row(1, 1), R.row(2, 1, 1)], 'cap', bug=1), 'detected')

    def test_an_alarm_at_the_same_cycle_as_the_wrong_output_is_a_detection(self):
        g = R.G
        f = [R.row(1, 1), R.row(0, 1, 1), R.row(3, 1), R.row(4, 1), R.row(5, 1)]
        self.assertEqual(C.first_differences(g, f), (1, 1))
        self.assertEqual(C.classify(g, f, 'done'), 'detected')

    def test_accounting_names_its_denominators(self):
        self.assertEqual(R.accounting(), (True, R.ACCOUNT_EXPECTED))
        ok, got = R.accounting(4)
        self.assertFalse(ok)
        self.assertEqual((got['target'], got['no_effect_share']), (10, 0.4))
        self.assertIsNone(C.tally([dict(cls='no_effect', excluded=False)])['detection_rate'])


class Statistics(unittest.TestCase):
    def test_exact_interval_matches_closed_forms_and_a_table_value(self):
        lo, hi = C.exact_interval(0, 10, 0.05)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 1 - 0.025 ** (1 / 10), places=9)
        lo, hi = C.exact_interval(10, 10, 0.05)
        self.assertAlmostEqual(lo, 0.025 ** (1 / 10), places=9)
        self.assertEqual(hi, 1.0)
        lo, hi = C.exact_interval(5, 10, 0.05)
        self.assertAlmostEqual(lo, 0.18709, places=4)
        self.assertAlmostEqual(hi, 0.81291, places=4)

    def test_binomial_tail_sums_agree(self):
        for k in range(0, 31, 5):
            self.assertAlmostEqual(C.binom_cdf(k, 30, 0.37) + (1 - C.binom_cdf(k, 30, 0.37)), 1.0)
        self.assertAlmostEqual(C.binom_cdf(20, 30, 0.5), 1 - C.binom_cdf(9, 30, 0.5), places=12)
        with self.assertRaises(ValueError):
            C.exact_interval(3, 2, 0.05)


class Structure(unittest.TestCase):
    def test_cones_and_exclusions_on_a_tiny_netlist(self):
        n = tiny_netlist()
        self.assertEqual(C.flip_flops(n, 't'), [('a', 1), ('b', 1)])
        cones = C.cones(n, 't')
        self.assertEqual(cones, {('a', 0): ['y'], ('b', 0): ['z']})
        self.assertEqual(C.exclusions(cones, ('y',)), [('b', 0, ['z'])])
        self.assertEqual(C.exclusions(cones, ('y', 'z')), [])

    def test_naive_list_contains_combinational_variables(self):
        naive = dict(C.declared_regs(R.RTL.read_text()))
        self.assertEqual(naive['next0'], 8)
        self.assertEqual(set(naive) - set(M.STATE), {'next0', 'next1'})
        self.assertFalse(R.check_inventory(sorted(naive.items()))[0])

    def test_injector_covers_every_bit_and_the_bugs_change_it(self):
        regs = sorted(M.STATE.items())
        text = C.injector(regs)
        self.assertEqual(text.count('force dut.'), 2 * sum(M.STATE.values()))
        self.assertEqual(text.count('release dut.'), sum(M.STATE.values()))
        self.assertIn('dut.error = ~dut.error', text)
        self.assertIn('0: dut.acc1[b] = ~dut.acc1[b]', C.injector(regs, 1))
        self.assertIn('dut.acc0[b] = dut.acc0[b];', C.injector(regs, 2))

    def test_ledger_is_stale_when_the_rtl_hash_or_cones_change(self):
        cones = {('error_code', 0): ['error_code'], ('error_code', 1): ['error_code'], ('done', 0): ['done']}
        ledger = json.loads(R.LEDGER.read_text())
        self.assertTrue(R.check_ledger(ledger, cones)[0])
        self.assertFalse(R.check_ledger(dict(ledger, rtl_sha256='0' * 64), cones)[0])
        self.assertFalse(R.check_ledger(ledger, {**cones, ('done', 0): ['error_code']})[0])
        self.assertFalse(R.check_ledger(dict(ledger, excluded=[dict(x, reason='') for x in ledger['excluded']]), cones)[0])


class Model(unittest.TestCase):
    def test_golden_run_and_population_size(self):
        g = M.run()
        self.assertEqual((g['status'], len(g['rows']), g['alarms']), ('done', 21, 1))
        self.assertEqual(len(M.population(21)), sum(M.STATE.values()) * 21 * 3)

    def test_stuck_bit_holds_and_flip_lasts_one_update(self):
        stuck = M.run(M.Fault('acc1', 0, M.STUCK, 0, 1))
        self.assertEqual(stuck['status'], 'abandon')
        flip = M.run(M.Fault('acc1', 3, M.FLIP, 6))
        self.assertEqual(flip['rows'], M.run()['rows'])

    def test_fixed_faults_classify_as_written(self):
        g = M.run()
        for fault, cls, status, _ in R.FIXED:
            with self.subTest(fault=fault.name()):
                m = M.run(fault)
                self.assertEqual((C.classify(g['rows'], m['rows'], m['status']), m['status']), (cls, status))


class Simulation(unittest.TestCase):
    def setUp(self):
        self.assertTrue(all(TOOLS.values()), f'Icarus and the YoWASP Yosys are required: {TOOLS}')

    def campaign(self, tmp):
        a = SimpleNamespace(iverilog=TOOLS['iverilog'], vvp=TOOLS['vvp'], yosys=TOOLS['yowasp-yosys'], timeout=60,
                            out=Path(tmp) / 'out', profile='smoke', seed=17)
        e = R.E.Evidence('t', a, [R.RTL], {}, ['x'])
        return R.Campaign(e, a)

    def test_extraction_under_tmp_matches_the_model(self):
        with temporary() as tmp:
            c = self.campaign(tmp)
            registers = C.flip_flops(c.synthesize(), R.TOP)
            self.assertEqual(R.check_inventory(registers)[0], True)

    def test_rtl_runs_match_the_model_and_a_bad_trace_is_refused(self):
        with temporary() as tmp:
            c = self.campaign(tmp)
            regs = sorted(M.STATE.items())
            faults = [f for f, *_ in R.FIXED]
            labels, records = c.compare(faults, c.simulate('clean', regs, faults))
            self.assertEqual(labels, set())
            self.assertTrue(all(r['match'] and r['readback'] for r in records))
            labels, _ = c.compare(faults, c.simulate('mut1', regs, faults, mutation=1))
            self.assertEqual(labels, {'FC_MODEL'})
            text = (c.out / 'runs' / 'clean' / 'trace.txt').read_text()
            self.assertEqual(len(R.parse_trace(text, len(faults))), len(faults) + 1)
            for broken in (text.replace('R 0 0 ', 'R 0 x ', 1), text.replace('\nE 3 ', '\nE 3 9 ', 1),
                           '\n'.join(line for line in text.splitlines() if not line.startswith('E 5 ')),
                           '\n'.join(line for line in text.splitlines() if line != text.splitlines()[0])):
                with self.assertRaises(ValueError):
                    R.parse_trace(broken, len(faults))


class RealRun(unittest.TestCase):
    def setUp(self):
        self.assertTrue(all(TOOLS.values()), f'Icarus and the YoWASP Yosys are required: {TOOLS}')

    def test_smoke_passes_and_broken_runs_fail(self):
        with temporary() as tmp:
            out = Path(tmp) / 'out'
            p = subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out)], capture_output=True, text=True, timeout=600)
            self.assertEqual(p.returncode, 0, p.stdout[-2000:] + p.stderr[-2000:])
            summary = json.loads((out / 'summary.json').read_text())
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual(summary['planned'], len(R.plan(SimpleNamespace(profile='smoke', seed=17))))
            self.assertEqual(len(list(ET.parse(out / 'junit.xml').getroot().iter('testcase'))), summary['planned'])
            report = json.loads((out / 'campaign.json').read_text())
            self.assertEqual((report['population']['faults'], report['excluded']['faults'], report['target']), (1827, 126, 1701))
            demo = subprocess.run([sys.executable, str(HERE / 'run.py'), '--demo-bug', '3', '--out', str(Path(tmp) / 'demo')],
                                  capture_output=True, text=True, timeout=600)
            self.assertEqual(demo.returncode, 1)
            failed = {r['id'] for r in json.loads((Path(tmp) / 'demo' / 'summary.json').read_text())['results'] if r['status'] != 'pass'}
            self.assertIn('golden', failed)
            missing = subprocess.run([sys.executable, str(HERE / 'run.py'), '--iverilog', 'no-such-iverilog', '--out', str(Path(tmp) / 'missing')],
                                     capture_output=True, text=True, timeout=600)
            self.assertEqual(missing.returncode, 1)

    def test_nightly_plan_adds_the_exhaustive_checks(self):
        smoke = R.plan(SimpleNamespace(profile='smoke', seed=17))
        nightly = R.plan(SimpleNamespace(profile='nightly', seed=17))
        self.assertEqual(set(nightly) - set(smoke), {'exhaustive', 'mutation1-rate-drop', 'sample-seed18', 'sample-seed19',
                                                      'sample-interval-seed18', 'sample-interval-seed19'})
        self.assertEqual((len(smoke), len(nightly)), (26, 32))


if __name__ == '__main__':
    unittest.main()
