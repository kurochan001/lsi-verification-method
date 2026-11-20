from pathlib import Path
import re, shutil, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import EXAMPLES, read_json, load_example

P = load_example('local-transition-fault')
A = P.A
YOSYS = shutil.which('yowasp-yosys') or shutil.which('yosys')
STA = shutil.which('sta') or shutil.which(str(P.ROOT / 'artifacts/toolchains/opensta-build/sta'))
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
TOOLS = ICARUS and YOSYS and STA


def run(out, *options, timeout=300):
    return subprocess.run([sys.executable, str(EXAMPLES / 'local-transition-fault/run.py'), '--out', str(out), *options],
                          capture_output=True, text=True, timeout=timeout)


def write_vectors(path, rows):
    path.write_text(''.join(' '.join(format(value, 'x') for value in row) + '\n' for row in rows))


class ModelTests(unittest.TestCase):
    def test_node_list_and_specification_give_the_same_next_state(self):
        self.assertTrue(all(A.capture(q, x) == A.functional(q, x) for q, x in A.PATTERNS))
        self.assertEqual(len({A.functional(q, 0) for q in range(16)}), 9)  # not every state is a successor

    def test_stuck_at_and_transition_coverage_have_their_own_denominators(self):
        report = A.report()
        self.assertEqual((report['stuck']['faults'], report['stuck']['detectable'], report['stuck']['undetectable']), (12, 12, []))
        self.assertEqual((report['transition']['faults'], report['transition']['detectable']), (12, 10))
        self.assertEqual(report['transition']['undetectable'], [
            dict(fault=[5, 1], reason='no-launch', stuck_at_detectable=True),
            dict(fault=[5, 0], reason='not-observed', stuck_at_detectable=True)])

    def test_a_transition_test_needs_the_launch_and_the_propagation(self):
        # n5 = !q0 & !q1 & q3 rises only towards states 8 and 12, and no state without n5 leads there
        self.assertFalse(any(A.launches(q, x, (5, 1)) for q, x in A.PATTERNS))
        # n5 falls from states 8 and 12, but the old value 1 only repeats what n2 already gives
        falling = [(q, x) for q, x in A.PATTERNS if A.launches(q, x, (5, 0))]
        self.assertTrue(falling)
        self.assertFalse(any(A.transition_detects(q, x, (5, 0)) for q, x in falling))
        self.assertTrue(A.stuck_detects(8, 0, (5, 0)) and any(A.stuck_detects(q, x, (5, 1)) for q, x in A.PATTERNS))
        # without the launch, the slow node changes nothing
        q, x = next((q, x) for q, x in A.PATTERNS if not A.launches(q, x, (0, 1)))
        self.assertEqual(A.transition_response(q, x, (0, 1)), P.good_response(q, x, 2))

    def test_selected_patterns_detect_every_detectable_fault(self):
        report = A.report()
        for fault in A.STUCK:
            self.assertTrue(any(A.stuck_detects(q, x, fault) for q, x in report['stuck']['patterns']))
        detected = {f for f in A.TRANSITION for q, x in report['transition']['patterns']
                    if A.transition_detects(q, x, f) and A.hazard_free(q, x, f)}
        self.assertEqual(len(detected), 10)

    def test_rows_that_depend_on_a_glitch_are_not_planned(self):
        self.assertFalse(A.hazard_free(1, 1, (4, 1)))  # n4 stays 1 while its cone changes
        with self.assertRaises(ValueError):
            P.Plan(1).transition(1, 1, (4, 1))
        for gap in (1, 4):
            for row in P.boundary_vectors(gap) + P.random_vectors(3, 300, gap):
                if row[0] == 1 and row[5] > 2:
                    self.assertTrue(A.hazard_free(row[1], row[2], (row[4], int(row[5] == 3))))


class PlanTests(unittest.TestCase):
    def test_only_the_capture_at_speed_expects_transition_faults_to_be_detected(self):
        fast, slow = P.boundary_vectors(1), P.boundary_vectors(4)
        self.assertEqual([row[:7] for row in fast], [row[:7] for row in slow])
        self.assertEqual(P.counts(fast), dict(fault_free=64, stuck_applied=12, stuck_detected=12,
                                              transition_applied=12, transition_detected=10))
        self.assertEqual(P.counts(slow), dict(fault_free=64, stuck_applied=12, stuck_detected=12,
                                              transition_applied=12, transition_detected=0))
        self.assertEqual(P.counts(P.escape_vectors(4)), dict(fault_free=0, stuck_applied=0, stuck_detected=0,
                                                             transition_applied=12, transition_detected=0))

    def test_seed_reproduction(self):
        self.assertEqual(P.random_vectors(3, 40, 1), P.random_vectors(3, 40, 1))
        self.assertNotEqual(P.random_vectors(3, 40, 1), P.random_vectors(4, 40, 1))

    def test_the_slow_configuration_records_what_it_cannot_see_as_diagnostics(self):
        args = SimpleNamespace(profile='smoke', seed=17, iterations=5, demo_bug=0)
        fast = {c['id']: c for c in P.make_cases(args, P.CONFIGS['at-speed'])}
        slow = {c['id']: c for c in P.make_cases(args, P.CONFIGS['slow'])}
        self.assertEqual(fast['detect-mutation1']['expected_failure'], 'TF_ESCAPE')
        self.assertEqual((slow['invisible-mutation1']['category'], slow['escaped-transition-faults']['category']),
                         ('diagnostic', 'diagnostic'))
        self.assertNotIn('detect-mutation1', slow)
        self.assertNotIn('escaped-transition-faults', fast)
        self.assertEqual((len(fast), len(slow)), (6, 7))

    def test_fault_site_cell_is_a_copy_of_the_buffer(self):
        text = P.site_library(P.LIBRARY.read_text())
        self.assertEqual((text.count('cell(TFSITE)'), text.count('cell(BUF)')), (1, 1))
        self.assertEqual(text.count('{'), text.count('}'))
        with self.assertRaises(ValueError):
            P.site_library(text)
        with self.assertRaises(ValueError):
            P.site_library('library(x) { cell(BUF) { pin(A) { }')

    def test_period_and_timing_module(self):
        self.assertAlmostEqual(P.choose_period(1.56), 1.7)
        self.assertAlmostEqual(P.choose_period(1.60), 1.7)
        self.assertAlmostEqual(P.choose_period(1.61), 1.75)
        module = P.timing_module(1.7, '../at-speed-m0/design.sdf', {'q_0_reg': (0.2, 0.1)})
        self.assertIn('PERIOD = 1.700', module)
        self.assertIn('$sdf_annotate("../at-speed-m0/design.sdf", tf_tb.dut);', module)
        self.assertIn('tf_tb.dut.q_0_reg.TSETUP = 0.2, tf_tb.dut.q_0_reg.THOLD = 0.1;', module)


@unittest.skipUnless(TOOLS, 'Icarus, Yosys and OpenSTA required')
class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'out'
        cls.result = run(cls.out, '--iterations', '30', '--yosys', YOSYS, '--sta', STA)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def simulate(self, image, rows, name):
        vectors = self.out / f'{name}.txt'
        write_vectors(vectors, rows)
        return subprocess.run(['vvp', str(self.out / image), f'+VECTORS={vectors}', f"+WAVE={self.out / (name + '.vcd')}"],
                              capture_output=True, text=True, timeout=60, cwd=self.out / 'at-speed-boundaries')

    def test_both_configurations_pass_and_detect_their_mutants(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        summary = read_json(self.out / 'summary.json')
        self.assertEqual((summary['planned'], summary['functional_pass'], summary['mutations_detected'], summary['diagnostics_pass']),
                         (13, 4, 7, 2))
        for name, item in read_json(self.out / 'coverage.json').items():
            self.assertEqual((item['hit'], item['missing']), (10, []), name)
        for configuration, mutations in (('at-speed', (1, 2, 3, 4)), ('slow', (2, 3, 4))):
            for mutation in mutations:
                message = read_json(self.out / f'{configuration}-detect-mutation{mutation}/result.json')['message']
                self.assertIn(P.LABELS[mutation], message)

    def test_observed_scan_out_detects_ten_slow_nodes_at_speed_and_none_with_a_slow_capture(self):
        def faults(case):
            log = (self.out / case / 'simulation.log').read_text()
            return re.findall(r'^FAULT site=(\d) kind=([34]) state=(\w) x=(\d) detected=(\d)$', log, re.M)
        fast, slow = faults('at-speed-boundaries'), faults('slow-escaped-transition-faults')
        self.assertEqual([row[:4] for row in fast], [row[:4] for row in slow])
        self.assertEqual(len({row[:2] for row in fast if row[4] == '1'}), 10)
        self.assertEqual({row[4] for row in slow}, {'0'})
        # the two faults without a test: every planned pattern applied, never detected
        self.assertEqual({row[4] for row in fast if row[0] == '5'}, {'0'})
        self.assertGreater(sum(row[0] == '5' for row in fast), 40)
        self.assertEqual(read_json(self.out / 'at-speed-boundaries/result.json')['counts']['stuck_detected'], 12)
        self.assertEqual(read_json(self.out / 'slow-boundaries/result.json')['counts']['stuck_detected'], 12)

    def test_static_timing_chose_the_period_and_the_sdf_file_reached_the_simulation(self):
        builds = read_json(self.out / 'builds.json')
        timing = builds['at-speed-m0']['preparation']['static_timing']
        self.assertGreaterEqual(min(timing['slack'].values()), 0)
        self.assertLess(timing['period'] - timing['need'], P.MARGIN + P.STEP)
        self.assertIn('-gspecify', builds['slow-m0']['command'])
        self.assertEqual(builds['slow-m0']['preparation']['reused_from'], 'at-speed-m0')
        self.assertEqual(builds['slow-m3']['preparation']['reused_from'], 'at-speed-m3')
        self.assertNotIn('reused_from', builds['at-speed-m4']['preparation'])
        self.assertIn('defparam', (self.out / 'at-speed-m0/tf_timing.v').read_text())
        self.assertNotIn('\nTIMING ', (self.out / 'at-speed-random-seed17/simulation.log').read_text().split('FAULT')[0])

    def test_a_period_shorter_than_the_longest_path_fails_the_fault_free_patterns(self):
        timing = read_json(self.out / 'at-speed-m0/timing.json')
        short = self.out / 'short.v'
        short.write_text((self.out / 'at-speed-m0/tf_timing.v').read_text()
                         .replace(f"PERIOD = {timing['period']:.3f}", f"PERIOD = {timing['need'] - 0.06:.3f}")
                         .replace('../at-speed-m0/', str(self.out / 'at-speed-m0') + '/'))
        subprocess.run(['iverilog', '-g2012', '-s', 'tf_tb', '-Ptf_tb.GAP=1', *P.iverilog_options({}), '-o', str(self.out / 'short.vvp'),
                        str(self.out / 'at-speed-m0/netlist.v'), str(P.CELLS), str(P.SITE_CELL), str(P.BENCH), str(short)],
                       check=True, capture_output=True, timeout=60)
        output = self.simulate('short.vvp', P.boundary_vectors(1), 'short').stdout
        self.assertIn('TIMING setup', output)
        self.assertIn('CHECK_FAIL TF_TIMING', output)

    def test_a_glitch_can_make_a_slow_node_visible_where_the_steady_values_say_it_is_not(self):
        # n4 is 1 before and after the launch of state 1, x=1, with a pulse to 0 in between:
        # slow to rise, it is still 0 at the capture. The plan leaves such rows out.
        row = [1, 1, 1, 2, 4, 3, P.good_response(1, 1, 2), 0, 0]
        self.assertFalse(A.transition_detects(1, 1, (4, 1)))
        rows = [[0, P.FLUSH, 0, 0, 0, 0, 0, 0, 0], row]
        self.assertIn('CHECK_FAIL TF_FALSE_ALARM', self.simulate('at-speed-m0.vvp', rows, 'glitch-fast').stdout)
        self.assertIn('RESULT PASS', self.simulate('slow-m0.vvp', rows, 'glitch-slow').stdout)

    def test_an_expected_detection_that_does_not_come_is_an_escape(self):
        q, x = A.report()['transition']['patterns'][0]
        fault = next(f for f in A.TRANSITION if A.transition_detects(q, x, f) and A.hazard_free(q, x, f))
        row = [1, q, x, 2, fault[0], 3 if fault[1] else 4, P.good_response(q, x, 2), 1, 4]
        rows = [[0, P.FLUSH, 0, 0, 0, 0, 0, 0, 0], row]
        self.assertIn('RESULT PASS', self.simulate('at-speed-m0.vvp', rows, 'escape-fast').stdout)
        self.assertIn('CHECK_FAIL TF_ESCAPE', self.simulate('slow-m0.vvp', rows, 'escape-slow').stdout)


@unittest.skipUnless(TOOLS, 'Icarus, Yosys and OpenSTA required')
class FaultTests(unittest.TestCase):
    def test_a_slow_capture_as_the_test_procedure_fails_only_at_speed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run(out, '--iterations', '2', '--demo-bug', '1', '--yosys', YOSYS, '--sta', STA)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(read_json(out / 'at-speed-boundaries/result.json')['status'], 'fail')
            self.assertEqual(read_json(out / 'slow-boundaries/result.json')['status'], 'pass')

    def test_a_design_mutant_fails_both_configurations(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run(out, '--iterations', '2', '--demo-bug', '3', '--yosys', YOSYS, '--sta', STA)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            for configuration in P.CONFIGS:
                record = read_json(out / f'{configuration}-boundaries/result.json')
                self.assertEqual((record['status'], record['message']), ('fail', 'checker failure: TF_SHIFT'))

    def test_a_missing_timing_tool_is_an_error_and_never_a_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run(out, '--configuration', 'at-speed', '--iterations', '2', '--yosys', YOSYS, '--sta', str(Path(tmp) / 'absent'))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual({read_json(p)['status'] for p in out.glob('*/result.json')}, {'error'})
            self.assertEqual(read_json(out / 'summary.json')['mutations_detected'], 0)


if __name__ == '__main__':
    unittest.main()
