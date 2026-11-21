from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json
P = load_example('local-dpi-model')
M = P.M
HERE = P.HERE


class PythonModelTests(unittest.TestCase):
    def test_published_check_values_and_bytewise_equals_block(self):
        self.assertEqual(M.block(M.DIGITS, 0xFFFF), 0x29B1)
        self.assertEqual(M.block(M.DIGITS, 0x0000), 0x31C3)
        crc = 0xFFFF
        for byte in M.DIGITS:
            crc = M.step(crc, byte)
        self.assertEqual(crc, 0x29B1)

    def test_outputs_hold_until_the_next_packet_and_clear_on_reset(self):
        rows = [P.RESET, *P.merge(P.packet([1, 2]), []), [1, *P.IDLE, *P.IDLE], P.RESET]
        outputs, blocks, counts = M.expected(rows, 0)
        crc = M.block([1, 2], 0)
        self.assertEqual([row[:3] for row in outputs], [(0, 0, 0), (0, 0, 0), (1, crc, 2), (0, crc, 2), (0, 0, 0)])
        self.assertEqual(blocks, [(0, 2, crc)])
        self.assertEqual((counts['packets0'], counts['packets1']), (1, 0))

    def test_length_saturates_and_reset_discards_an_open_packet(self):
        rows = [P.RESET, *P.merge(P.packet(bytes(300)), P.partial([9, 9])), P.RESET, *P.merge([], P.packet([7]))]
        outputs, _, _ = M.expected(rows, 0xFFFF)
        self.assertEqual(outputs[300][2], 255)
        self.assertEqual(outputs[-1][3:], (1, M.block([7], 0xFFFF), 1))

    def test_unknown_digits_read_as_zero_and_are_counted_by_validity(self):
        self.assertEqual(M.parse_data('0011x0z1'), (0b00110001, 2))
        for bad in ('0011', '0011x0021', '0011x00 '):
            with self.assertRaises(ValueError):
                M.parse_data(bad)
        counts = M.expected(P.unknown_on_valid(), 0)[2]
        self.assertEqual((counts['unknown_valid'], counts['unknown_idle']), (1, 0))
        self.assertGreater(M.expected(P.directed(), 0)[2]['unknown_idle'], 0)
        self.assertEqual(M.expected(P.directed(), 0)[2]['unknown_valid'], 0)


class PlanTests(unittest.TestCase):
    def test_directed_vectors_reach_every_stimulus_goal(self):
        _, required = P.catalog()
        stimulus = {goal for goal in required if goal.split('/')[0] in ('stream', 'reset', 'instances')} | {'unknown/idle-data'}
        self.assertEqual(P.goals(P.directed()), stimulus)
        self.assertNotIn('instances/interleaved', P.goals(P.single_channel()))
        self.assertNotIn('reset/mid-packet', P.goals(P.single_channel()))

    def test_random_vectors_follow_the_seed(self):
        self.assertEqual(P.randomized(17, 24), P.randomized(17, 24))
        self.assertNotEqual(P.randomized(17, 24), P.randomized(18, 24))
        self.assertIn(P.RESET, P.randomized(17, 24)[3:])

    def test_plan_sizes_and_unique_identifiers(self):
        for profile, total in (('smoke', 58), ('nightly', 74)):
            ids = P.plan_ids(P.CONFIGS, P.vector_sets(profile, 17))
            self.assertEqual((len(ids), len(set(ids))), (total, total))
        self.assertEqual(len(P.plan_ids({'init-0000': 0}, P.vector_sets('smoke', 17))), 36)

    def test_every_credited_goal_is_in_the_catalog_and_the_reverse(self):
        data, required = P.catalog()
        source = (HERE / 'run.py').read_text()
        named = set(re.findall(r"'((?:stream|reset|instances|unknown|dpi|types|route|model)/[a-z-]+)'", source))
        self.assertEqual(named, required)
        self.assertEqual((len(data['requirements']), len(required)), (6, 30))

    def test_catalog_rejects_duplicate_goals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'requirements.json'
            path.write_text('{"requirements":[{"goals":["a","a"]}]}')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                P.catalog(path)

    def test_cross_check_names_each_kind_of_difference(self):
        rows = P.directed()
        outputs, blocks, counts = M.expected(rows, 0xFFFF)
        self.assertEqual(P.cross(rows, 0xFFFF, (outputs, blocks, counts)), [])
        target = next(i for i, row in enumerate(outputs) if row[0])
        for offset, label in ((0, 'MODEL_DONE'), (1, 'MODEL_CRC'), (2, 'MODEL_LEN'), (4, 'MODEL_CRC')):
            changed = list(outputs)
            row = list(changed[target])
            row[offset] ^= 1
            changed[target] = tuple(row)
            self.assertEqual(P.cross(rows, 0xFFFF, (changed, blocks, counts)), [label])
        wrong = [(blocks[0][0], blocks[0][1], blocks[0][2] ^ 1), *blocks[1:]]
        self.assertEqual(P.cross(rows, 0xFFFF, (outputs, wrong, counts)), ['MODEL_BLOCK'])
        self.assertEqual(P.cross(rows, 0xFFFF, (outputs[:-1], blocks, counts)), ['MODEL_COUNT'])
        self.assertEqual(P.cross(rows, 0xFFFF, (outputs, blocks[1:], counts)), ['MODEL_COUNT'])
        self.assertEqual(P.cross(rows, 0xFFFF, (outputs, blocks, dict(counts, unknown_idle=0))), ['MODEL_COUNT'])

    def test_probe_and_count_parsers_reject_duplicates(self):
        self.assertEqual(P.probe_values('PROBE a=1\nnoise\nPROBE b=x\n'), dict(a='1', b='x'))
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            P.probe_values('PROBE a=1\nPROBE a=2\n')
        self.assertIsNone(P.simulation_counts('COUNT a=1\nCOUNT a=1\n'))
        self.assertEqual(len(P.PROBE), 15)


class CModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.cli = cls.dir / 'packet_cli'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(HERE / 'model'), '-o', str(cls.cli),
                        str(HERE / 'model/packet_cli.c'), str(HERE / 'model/packet_model.c')], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def model(self, name, rows, init, fault=0, instances=2):
        vectors, expected, summary = (self.dir / f'{name}.{kind}' for kind in ('vectors', 'expected', 'summary'))
        P.write_vectors(vectors, rows)
        done = subprocess.run([str(self.cli), str(init), str(fault), str(instances), str(vectors), str(expected), str(summary)],
                              capture_output=True, text=True, timeout=30)
        return done.returncode, (P.read_cli(expected, summary) if done.returncode == 0 else None)

    def test_c_model_agrees_with_python_for_both_start_values(self):
        for init in P.CONFIGS.values():
            for name, rows in (('directed', P.directed()), ('random', P.randomized(5, 40))):
                code, files = self.model(f'{name}{init}', rows, init)
                self.assertEqual((code, P.cross(rows, init, files)), (0, []))

    def test_each_model_fault_is_reported_with_its_labels(self):
        rows = P.directed()
        for fault, labels in P.MODEL_FAULTS.items():
            code, files = self.model(f'fault{fault}', rows, 0xFFFF, fault)
            self.assertEqual((code, P.cross(rows, 0xFFFF, files)), (0, labels), fault)

    def test_shared_state_is_invisible_with_one_instance(self):
        rows = P.single_channel()
        code, files = self.model('single', rows, 0, 2, instances=1)
        self.assertEqual((code, P.cross(rows, 0, files)), (0, []))
        code, files = self.model('pair', rows, 0, 2, instances=2)
        self.assertTrue(P.cross(rows, 0, files))

    def test_model_program_rejects_bad_arguments_and_rows(self):
        rows = P.unknown_on_valid()
        self.assertEqual(self.model('ok', rows, 0)[0], 0)
        self.assertEqual(self.model('ok', rows, 0)[1][2]['unknown_valid'], 1)
        self.assertEqual(self.model('init', rows, 65536)[0], 2)
        self.assertEqual(self.model('fault', rows, 0, 6)[0], 2)
        self.assertEqual(self.model('instances', rows, 0, 0, 3)[0], 2)
        self.assertEqual(self.model('busy', P.directed(), 0, 0, 1)[0], 2)
        self.assertEqual(self.model('digit', [[1, 1, '00000002', 1, *P.IDLE]], 0)[0], 2)
        self.assertEqual(self.model('short', [[1, 1, '0000000', 1, *P.IDLE]], 0)[0], 2)

    def test_file_route_passes_and_reports_a_mutation_and_unknown_data(self):
        rows = P.directed()
        _, _ = self.model('route', rows, 0xFFFF)
        outcomes = {}
        for name, mutation, vectors in (('good', 0, 'route'), ('mutant', 3, 'route'), ('unknown', 0, 'x')):
            if vectors == 'x':
                self.model('x', P.unknown_on_valid(), 0xFFFF)
            binary = self.dir / f'{name}.vvp'
            subprocess.run(['iverilog', '-g2012', '-s', 'file_tb', '-Pfile_tb.INIT=65535', f'-Pfile_tb.MUTATION={mutation}',
                            '-o', str(binary), str(P.RTL), str(HERE / 'tb/file_tb.sv')], check=True, capture_output=True)
            done = subprocess.run(['vvp', str(binary), f'+VECTORS={self.dir / (vectors + ".vectors")}',
                                   f'+EXPECTED={self.dir / (vectors + ".expected")}', f'+OBSERVED={self.dir / (name + ".observed")}'],
                                  capture_output=True, text=True, timeout=60)
            outcomes[name] = (done.returncode != 0, re.findall(r'^CHECK_FAIL (\w+)$', done.stdout, re.M),
                              re.findall(r'^RESULT PASS checks=(\d+)$', done.stdout, re.M))
        self.assertEqual(outcomes['good'], (False, [], [str(len(rows))]))
        self.assertEqual(outcomes['mutant'], (True, ['SUM_LEN'], []))
        self.assertEqual(outcomes['unknown'], (True, ['SUM_X_INPUT'], []))


class RunnerTests(unittest.TestCase):
    def run_example(self, out, *options):
        return subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out), *options],
                              capture_output=True, text=True, timeout=300)

    def test_missing_verilator_fails_closed_with_the_full_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            done = self.run_example(out, '--verilator', str(Path(tmp) / 'no-such-verilator'))
            self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
            summary = read_json(out / 'summary.json')
            self.assertFalse(summary['success'])
            self.assertTrue(summary['complete'])
            status = {r['id']: r['status'] for r in summary['results']}
            self.assertEqual(len(status), 58)
            self.assertEqual(status['init-ffff-dpi-build'], 'fail')
            self.assertEqual(status['init-ffff-dpi-directed'], 'fail')
            self.assertEqual(status['init-ffff-dpi-x-blind'], 'fail')
            self.assertEqual(status['model-fault-5-common-mode-miss'], 'fail')
            # The parts that need no DPI still ran and passed.
            for name in ('cli-build', 'known-answer', 'init-ffff-cross-directed', 'init-ffff-file-directed',
                         'init-0000-file-mutant-5', 'init-ffff-file-x-on-valid', 'model-fault-4-cross'):
                self.assertEqual(status[name], 'pass', name)
            self.assertEqual(status['requirements-and-coverage'], 'fail')
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), len(suite.findall('testcase'))), ('58', 58))

    def test_existing_output_and_bad_options_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_example(tmp).returncode, 2)
            self.assertEqual(self.run_example(Path(tmp) / 'a', '--jobs', '0').returncode, 2)
            self.assertEqual(self.run_example(Path(tmp) / 'b', '--configuration', 'init-1234').returncode, 2)
            self.assertFalse((Path(tmp) / 'a').exists())


if __name__ == '__main__':
    unittest.main()
