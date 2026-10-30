from pathlib import Path
import re, shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import read_json, run_example, load_example

P = load_example('local-gate-sim')
YOSYS = shutil.which('yowasp-yosys') or shutil.which('yosys')
ICARUS = shutil.which('iverilog') and shutil.which('vvp')


def simulate_rtl(rtl, mutation, rows, tmp):
    vectors = tmp / 'v.txt'
    vectors.write_text(''.join(' '.join(format(x, 'x') for x in row) + '\n' for row in rows))
    subprocess.run(['iverilog', '-g2012', '-s', 'arbiter_tb', f'-Parbiter_tb.MUTATION={mutation}', '-o', str(tmp / 's.vvp'),
                    str(rtl), str(P.SOURCES[1])], check=True, capture_output=True, timeout=60)
    return subprocess.run(['vvp', str(tmp / 's.vvp'), f'+VECTORS={vectors}', f"+WAVE={tmp / 'w.vcd'}"],
                          capture_output=True, text=True, timeout=60).stdout


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-gate-sim'
    GOALS = 9

    def test_model_grants_the_lowest_request_for_four_beats_then_idles_two_cycles(self):
        m = P.Model()
        rows = [m.step(1, req) for req in (0b1010, 0, 0, 0, 0, 0, 0b0110, 0)]
        self.assertEqual([r[0] for r in rows], [0, 1, 1, 1, 1, 0, 0, 1])
        self.assertEqual([r[1] for r in rows], [0, 0, 0, 0, 1, 0, 0, 0])
        self.assertEqual(rows[1][2], 1)
        self.assertEqual(rows[7][2], 1)
        self.assertEqual(rows[5][3], 1)
        self.assertEqual(m.step(0, 0b1111)[0], 1)
        self.assertEqual(m.step(1, 0), [0, 0, 0, 0])

    def test_fixed_scenario_covers_conflicts_the_wrap_and_a_request_change_at_arbitration(self):
        rows = P.boundary_vectors()
        arbitrated = [rows[i - 1][1] for i in range(1, len(rows)) if rows[i][0] and rows[i][2] and not rows[i - 1][2]]
        self.assertTrue({0b0011, 0b1001, 0b1111} <= set(arbitrated))
        self.assertTrue(any(a[5] == 255 and b[5] == 0 and a[0] and b[0] for a, b in zip(rows, rows[1:])))
        changed = [i for i in range(2, len(rows)) if rows[i][0] and rows[i][2] and not rows[i - 1][2]
                   and P.lowest(rows[i - 2][1] or 1) != P.lowest(rows[i - 1][1])]
        self.assertTrue(changed, 'mutation 4 needs a request that changes between the gap and the arbitration')

    @unittest.skipUnless(ICARUS, 'Icarus required')
    def test_rtl_result_of_mutation4_depends_on_the_order_of_two_blocks(self):
        line = '    always @(posedge clk) pick_q = pick;\n'
        text = P.RTL.read_text()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            swapped = tmp / 'burst_arbiter.sv'
            swapped.write_text(text.replace(line, '').replace('endmodule\n', line + 'endmodule\n'))
            rows = P.boundary_vectors()
            self.assertIn('RESULT PASS', simulate_rtl(P.RTL, 4, rows, tmp))
            self.assertIn('CHECK_FAIL', simulate_rtl(swapped, 4, rows, tmp))

    def test_real_rtl_all_configurations_and_mutants(self):
        if not (ICARUS and YOSYS):
            self.skipTest('Icarus and Yosys required')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example(self.EXAMPLE, out, '--iterations', '3', '--yosys', YOSYS)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertEqual((summary['planned'], summary['mutations_detected'], summary['diagnostics_pass']), (12, 4, 4))
            for name, item in read_json(out / 'coverage.json').items():
                self.assertEqual((item['hit'], item['missing']), (self.GOALS, []), name)
            log = (out / 'gate-m2/synthesis.log').read_text()
            self.assertIn('parallel_case', log)
            self.assertIn('translate_off', log)
            for mutation in range(5):
                netlist = (out / f'gate-m{mutation}/netlist.v').read_text()
                self.assertEqual(set(re.findall(r'\\\$_(DFF\w*?)_ ', netlist)), {'DFF_P'})
                self.assertNotIn('initial', netlist)

    def test_demo_faults_make_normal_regression_fail(self):
        if not (ICARUS and YOSYS):
            self.skipTest('Icarus and Yosys required')
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, 5):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run_example(self.EXAMPLE, out, '--iterations', '2', '--demo-bug', str(fault), '--yosys', YOSYS)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(read_json(out / 'gate-boundaries/result.json')['status'], 'fail')
                    self.assertEqual(read_json(out / 'rtl-boundaries/result.json')['status'], 'pass')


if __name__ == '__main__':
    unittest.main()
