import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load('tlm_platform_test_model', HERE / 'model.py')
R = load('tlm_platform_test_runner', HERE / 'run.py')
BASIC = dict(irqs=8, load=150, seed=0x1234, race=0)


def systemc_config():
    found = shutil.which('lsi-systemc-config')
    if found:
        return found
    candidate = ROOT / 'artifacts/vci-soclib-20261102/systemc-install/bin/lsi-systemc-config'
    return str(candidate) if candidate.is_file() else 'lsi-systemc-config'


class ModelTests(unittest.TestCase):
    def test_expected_run_follows_the_register_contract(self):
        e = M.expected(BASIC)
        self.assertEqual(e['notes'], [('irq_level_masked', 0)] + [('irq', k) for k in range(8)])
        expired = [d for op, a, d, _ in e['access'] if (op, a) == ('R', M.EXPIRED)]
        self.assertEqual(expired, list(range(1, 9)))
        status = [d for op, a, d, _ in e['access'] if (op, a) == ('R', M.STATUS)]
        self.assertEqual(status[:3], [3, 2, 0])
        self.assertEqual(status[3:], [1] * 8)
        self.assertEqual([a for op, a, d, err in e['access'] if err], list(M.HOLES))
        memory = e['memory']
        self.assertEqual(memory[:16], [M.pattern(0x1234, k) for k in range(16)])
        self.assertEqual(memory[16:24], [(k + 1) | 1 << 16 for k in range(8)])
        self.assertEqual(memory[49:54], [0x1f, 0, 0x23, 0, 150])
        self.assertEqual(memory[48], memory[39])
        self.assertTrue(all(v == 0 for v in memory[24:32] + memory[40:48] + memory[54:]))

    def test_race_only_adds_a_count_read_whose_value_is_open(self):
        quiet, race = M.expected(BASIC), M.expected(dict(BASIC, race=1))
        counts = [x for x in race['access'] if x[1] == M.COUNT]
        self.assertEqual(len(counts), 8)
        self.assertTrue(all(x[2] is None for x in counts))
        self.assertEqual([x for x in race['access'] if x[1] != M.COUNT], quiet['access'])
        self.assertEqual(race['memory'], quiet['memory'])

    def test_pattern_matches_the_c_driver_formula(self):
        # 32-bit wrap of seed*0x9e3779b1 ^ index*0x85ebca6b ^ index<<7, then x ^ x>>13
        self.assertEqual(M.pattern(0, 0), 0)
        self.assertEqual(M.pattern(1, 0), 0x9e3779b1 ^ (0x9e3779b1 >> 13))
        x = (0x85ebca6b * 3) & 0xffffffff ^ (3 << 7)
        self.assertEqual(M.pattern(0, 3), x ^ (x >> 13))

    def test_inputs_are_rejected_outside_the_supported_range(self):
        for bad in (dict(BASIC, irqs=0), dict(BASIC, irqs=17), dict(BASIC, load=0), dict(BASIC, load=0x10000)):
            with self.assertRaises(ValueError):
                M.expected(bad)

    def log(self, config=BASIC, mutate=None):
        e = M.expected(config)
        lines = []
        notes = iter(e['notes'])
        pending = next(notes, None)
        for op, a, d, err in e['access']:
            if pending and pending[0] == 'irq_level_masked' and a == M.MEM + 0xc8:
                lines.append(f'NOTE {pending[0]} {pending[1]:08x}'); pending = next(notes, None)
            if pending and pending[0] == 'irq' and (op, a) == ('R', M.STATUS) and d == 1:
                lines.append(f'NOTE {pending[0]} {pending[1]:08x}'); pending = next(notes, None)
            lines.append(f'ACCESS {op} {a:08x} {(d or 0):08x} {err}')
        lines += [f'MEM {i:02x} {v:08x}' for i, v in enumerate(e['memory'])]
        lines += ['RESULT app=0 cycles=1', 'END']
        if mutate:
            lines = mutate(lines)
        return '\n'.join(lines) + '\n'

    def test_a_complete_log_matches_and_each_category_is_reported_first(self):
        parsed = M.parse(self.log())
        self.assertTrue(parsed['complete'])
        self.assertEqual(M.differences(parsed, M.expected(BASIC)), [])
        cases = {
            'PLAT_EVENT': lambda ls: [l.replace('NOTE irq_level_masked 00000000', 'NOTE irq_level_masked 00000001') for l in ls],
            'PLAT_ACCESS': lambda ls: [l.replace('ACCESS R 00001010 00000002 0', 'ACCESS R 00001010 00000003 0') for l in ls],
            'PLAT_MEMORY': lambda ls: [l.replace('MEM 3f 00000000', 'MEM 3f 00000001') for l in ls],
            'PLAT_RESULT': lambda ls: [l.replace('RESULT app=0', 'RESULT app=-2') for l in ls],
        }
        for label, mutate in cases.items():
            found = M.differences(M.parse(self.log(mutate=mutate)), M.expected(BASIC))
            self.assertEqual([c for c, _ in found], [label], label)

    def test_incomplete_duplicate_and_malformed_logs_are_not_complete(self):
        self.assertFalse(M.parse(self.log(mutate=lambda ls: ls[:-1]))['complete'])
        self.assertFalse(M.parse(self.log(mutate=lambda ls: [l for l in ls if not l.startswith('MEM 3f')]))['complete'])
        self.assertFalse(M.parse(self.log(mutate=lambda ls: ls + ['CHECK_FAIL PLAT_TIMEOUT']))['complete'])
        for broken in (lambda ls: ls + ['MEM 00 00000000'], lambda ls: ls + ['RESULT app=0 cycles=2'],
                       lambda ls: ls + ['ACCESS X 00000000 00000000 0'], lambda ls: ls + ['MEM 40 00000000']):
            with self.assertRaises(ValueError):
                M.parse(self.log(mutate=broken))

    def test_masked_hides_only_count_read_data(self):
        record = dict(access=[('R', M.COUNT, 7, 0), ('R', M.EXPIRED, 2, 0), ('W', M.COUNT, 5, 0)])
        self.assertEqual(M.masked(record)['access'], [('R', M.COUNT, None, 0), ('R', M.EXPIRED, 2, 0), ('W', M.COUNT, 5, 0)])
        self.assertFalse(M.same_access([('R', M.COUNT, None, 0)], [('R', M.COUNT, 1, 1)]))


class PlanTests(unittest.TestCase):
    def test_plan_sizes_and_unique_ids(self):
        for profile, size in (('smoke', 28), ('nightly', 36)):
            ids = R.plan(profile, 17)
            self.assertEqual(len(ids), size)
            self.assertEqual(len(set(ids)), size)

    def test_scenarios_are_reproducible_and_in_range(self):
        self.assertEqual(R.scenarios('nightly', 5), R.scenarios('nightly', 5))
        self.assertNotEqual(R.scenarios('smoke', 5), R.scenarios('smoke', 6))
        for config in R.scenarios('nightly', 3).values():
            M.expected(config)
            self.assertTrue(70 <= config['load'] <= 400 or config['load'] in (90, 150))

    def test_timing_follows_the_bus_wait(self):
        self.assertEqual(R.timing(BASIC, 0)['lead'], 2)
        self.assertEqual(R.timing(BASIC, 2)['lead'], 4)
        self.assertGreater(R.timing(BASIC, 2)['cycle_limit'], R.timing(BASIC, 0)['cycle_limit'])

    def test_every_catalog_goal_has_a_source(self):
        _, goals = R.E.C.catalog(R.REQUIREMENTS)
        record = dict(covers={'race/clear-set', 'bus/wait-state', 'timer/period'}, notes=M.expected(BASIC)['notes'],
                      access=M.expected(BASIC)['access'], memory=M.expected(BASIC)['memory'])
        self.assertEqual(R.observe(record) | R.NEGATIVE_GOALS, goals)
        self.assertNotIn('bus/unmapped-error', R.observe(dict(record, access=record['access'][16:18])))

    def test_mutation_labels_are_known_categories(self):
        self.assertTrue(all(label in M.CATEGORIES for _, label in R.RTL_MUTATIONS.values()))
        self.assertTrue(all(name in R.scenarios('smoke', 17) for name, _ in R.RTL_MUTATIONS.values()))


class RealRunTests(unittest.TestCase):
    def test_smoke_passes_and_a_missing_simulator_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = subprocess.run([sys.executable, str(HERE / 'run.py'), '--systemc-config', systemc_config(), '--out', str(out)],
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])
            summary = json.loads((out / 'summary.json').read_text())
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual(len(list(ET.parse(out / 'junit.xml').getroot().iter('testcase'))), 28)
            details = {r['id']: r['detail'] for r in summary['results']}
            for m, (_, label) in R.RTL_MUTATIONS.items():
                self.assertEqual(details[f'rtl-wait0/mutation{m}']['observed_first'], label)
            self.assertEqual(details['tlm-wait0/fault-ie']['observed_first'], 'PLAT_EVENT')
            # The repository runner re-verifies this record with tools/systemc.py.
            R.SC.verify(json.loads((out / 'systemc-source.json').read_text()))
            self.assertGreaterEqual(len(json.loads((out / 'tlm-headers.json').read_text())), 20)
            race = json.loads((out / 'runs/rtl-wait0/race/result.json').read_text())
            self.assertIn('race/clear-set', race['parsed']['covers'])
            tlm_race = json.loads((out / 'runs/tlm-wait0/race/result.json').read_text())
            self.assertNotIn('race/clear-set', tlm_race['parsed']['covers'])
            broken = subprocess.run([sys.executable, str(HERE / 'run.py'), '--systemc-config', systemc_config(),
                                     '--verilator', 'no-such-verilator', '--out', str(Path(tmp) / 'broken')], capture_output=True, text=True)
            self.assertEqual(broken.returncode, 1)
            failed = [r['id'] for r in json.loads((Path(tmp) / 'broken/summary.json').read_text())['results'] if r['status'] != 'pass']
            self.assertIn('toolchain', failed)

    def test_existing_output_and_bad_options_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            for extra in (['--jobs', '0'], ['--build-timeout', 'nan'], ['--out', tmp]):
                args = [sys.executable, str(HERE / 'run.py'), *(['--out', str(Path(tmp) / 'x')] if extra[0] != '--out' else []), *extra]
                self.assertEqual(subprocess.run(args, capture_output=True, text=True).returncode, 2, extra)


if __name__ == '__main__':
    unittest.main()
