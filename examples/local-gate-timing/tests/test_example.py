from pathlib import Path
import shutil, subprocess, sys, tempfile, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import EXAMPLES, read_json, load_example

P = load_example('local-gate-timing')
YOSYS = shutil.which('yowasp-yosys') or shutil.which('yosys')
STA = shutil.which('sta') or (shutil.which(str(P.ROOT / 'artifacts/toolchains/opensta-build/sta')))
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
TOOLS = ICARUS and YOSYS and STA
SDF = '''(DELAYFILE
 (CELL (CELLTYPE "NAND2") (INSTANCE _1_) (DELAY (ABSOLUTE (IOPATH A Y (0.100::0.100)))))
 (CELL (CELLTYPE "DFFE") (INSTANCE a_q_0_reg)
  (TIMINGCHECK (HOLD D (posedge CLK) (0.100::0.100)) (SETUP D (posedge CLK) (0.200::0.200))
   (HOLD E (posedge CLK) (0.100::0.100)) (SETUP E (posedge CLK) (0.200::0.200))))
 (CELL (CELLTYPE "DFF") (INSTANCE done_reg)
  (TIMINGCHECK (HOLD D (posedge CLK) (0.100::0.100)) (SETUP D (posedge CLK) (0.200::0.200))))
)'''
FLOP_BENCH = '''`timescale 1ns/1ps
module flop_tb;
    reg clk = 0, d = 0, e = 1, keep; wire q, qe; real at;
    DFF #(.TSETUP(0.2), .THOLD(0.1)) plain(.CLK(clk), .D(d), .Q(q));
    DFFE #(.TSETUP(0.2), .THOLD(0.1)) enabled(.CLK(clk), .D(d), .E(e), .Q(qe));
    always #5 clk = ~clk;
    initial begin
        if (!$value$plusargs("AT=%f", at) || !$value$plusargs("KEEP=%b", keep)) $fatal(1, "arguments required");
        #12 d = 1;          // far from any edge: both flops take it at 15
        #5 e = keep;        // the second flop is disabled from here, or not
        #(8 + at) d = 0;    // `at` relative to the edge at 25
        #6 $display("Q %b %b %0d", q, qe, timing_pkg::violations); $finish;
    end
endmodule
'''


def run(out, *options, timeout=300):
    return subprocess.run([sys.executable, str(EXAMPLES / 'local-gate-timing/run.py'), '--out', str(out), *options],
                          capture_output=True, text=True, timeout=timeout)


class UnitTests(unittest.TestCase):
    def test_expected_result_doubles_the_product_only_with_cfg(self):
        self.assertEqual((P.expected(63, 63, 0), P.expected(63, 63, 1), P.expected(0, 63, 1)), (3969, 7938, 0))

    def test_fixed_scenario_has_what_each_mutant_needs(self):
        rows = P.boundary_vectors()
        operations = [r for r in rows if r[0] == 1]
        self.assertEqual(rows[0][0], 0)
        self.assertTrue(any(r[0] == 2 for r in rows))
        # mutant 2: cfg changes in a start cycle (no idle cycle) and the product is not zero
        changes = [(p, r) for p, r in zip(operations, operations[1:]) if p[3] != r[3] and r[4] == 0 and r[1] * r[2]]
        self.assertTrue(changes)
        self.assertTrue(any(r[1] == r[2] == 63 for r in operations))
        self.assertEqual(P.counts(rows), dict(operations=len(operations), aborted=1, timing_violations=0))

    def test_seed_reproduction(self):
        self.assertEqual(P.random_vectors(3, 20), P.random_vectors(3, 20))
        self.assertNotEqual(P.random_vectors(3, 20), P.random_vectors(4, 20))

    def test_flops_are_named_after_their_outputs(self):
        netlist = ('  DFFE _5_ (\n    .CLK(clk),\n    .D(b[0]),\n    .E(load),\n    .Q(b_q[0])\n  );\n'
                   '  DFF _6_ (\n    .CLK(clk_done),\n    .D(fire),\n    .Q(done)\n  );\n  CKDLY \\g_skew.skew  (\n    .A(clk)\n  );\n')
        text, names = P.name_registers(netlist)
        self.assertEqual(names, ['b_q_0_reg', 'done_reg'])
        self.assertIn('DFFE b_q_0_reg (', text)
        self.assertIn('CKDLY skew (', text)
        with self.assertRaises(ValueError):  # two flops on one net cannot both be named
            P.name_registers(netlist + netlist)

    def test_check_limits_come_from_the_sdf_file_and_must_cover_every_flop(self):
        self.assertEqual(P.check_limits(SDF, ['a_q_0_reg', 'done_reg']), {'a_q_0_reg': (0.2, 0.1), 'done_reg': (0.2, 0.1)})
        with self.assertRaises(ValueError):
            P.check_limits(SDF, ['a_q_0_reg', 'done_reg', 'busy_reg'])
        with self.assertRaises(ValueError):  # D and E disagree
            P.check_limits(SDF.replace('(SETUP E (posedge CLK) (0.200::0.200))', '(SETUP E (posedge CLK) (0.300::0.300))'), ['a_q_0_reg', 'done_reg'])

    def test_period_is_set_by_the_group_that_needs_most(self):
        self.assertAlmostEqual(P.choose_period(dict(multicycle=3.28, single=0.9, input=0.52, cfg=0.2)), 1.75)
        self.assertAlmostEqual(P.choose_period(dict(multicycle=3.28, single=1.9, input=0.52, cfg=0.2)), 2.0)
        self.assertAlmostEqual(P.choose_period(dict(multicycle=3.28, single=0.9, input=1.0, cfg=0.2)), 2.1)

    def test_timing_module_annotates_and_sets_limits_only_with_an_sdf_file(self):
        plain = P.timing_module(10, 5)
        self.assertIn('PERIOD = 10.000, CFG_AT = 5.000', plain)
        self.assertNotIn('sdf_annotate', plain)
        timed = P.timing_module(1.75, 0.875, '../sdf-m0/design.sdf', {'done_reg': (0.2, 0.1)})
        self.assertIn('$sdf_annotate("../sdf-m0/design.sdf", mc_tb.g_gate.dut);', timed)
        self.assertIn('mc_tb.g_gate.dut.done_reg.TSETUP = 0.2, mc_tb.g_gate.dut.done_reg.THOLD = 0.1;', timed)

    def test_only_the_sdf_view_compiles_with_delays(self):
        self.assertEqual(P.iverilog_options({'GATE': 2}), ['-gspecify', '-ginterconnect', '-Tmax'])
        self.assertEqual(P.iverilog_options({'GATE': 1}), [])


@unittest.skipUnless(ICARUS, 'Icarus required')
class FlopModelTests(unittest.TestCase):
    """The flops check their own data pin, because Icarus has no $setup or $hold."""

    def outcome(self, at, enable=1):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'flop_tb.sv').write_text(FLOP_BENCH)
            subprocess.run(['iverilog', '-g2012', '-s', 'flop_tb', '-o', str(tmp / 's.vvp'), str(P.CELLS), str(tmp / 'flop_tb.sv')],
                           check=True, capture_output=True, timeout=60)
            output = subprocess.run(['vvp', str(tmp / 's.vvp'), f'+AT={at}', f'+KEEP={enable}'], capture_output=True, text=True, timeout=60).stdout
            return next(line for line in output.splitlines() if line.startswith('Q ')).split()[1:]

    def test_a_change_outside_the_window_is_taken_or_missed_cleanly(self):
        self.assertEqual(self.outcome(-0.25), ['0', '0', '0'])
        self.assertEqual(self.outcome(0.15), ['1', '1', '0'])

    def test_a_change_inside_the_setup_or_hold_window_gives_x(self):
        self.assertEqual(self.outcome(-0.15), ['x', 'x', '2'])
        self.assertEqual(self.outcome(0.05), ['x', 'x', '2'])

    def test_a_disabled_flop_does_not_look_at_its_data_pin(self):
        self.assertEqual(self.outcome(-0.15, enable=0), ['x', '1', '1'])
        self.assertEqual(self.outcome(0.05, enable=0), ['x', '1', '1'])


@unittest.skipUnless(TOOLS, 'Icarus, Yosys and OpenSTA required')
class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'out'
        cls.result = run(cls.out, '--iterations', '6', '--yosys', YOSYS, '--sta', STA)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_views_pass_and_only_the_sdf_view_detects_the_mutants(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        summary = read_json(self.out / 'summary.json')
        self.assertEqual((summary['planned'], summary['functional_pass'], summary['mutations_detected'], summary['diagnostics_pass']), (15, 6, 3, 6))
        for name, item in read_json(self.out / 'coverage.json').items():
            self.assertEqual((item['hit'], item['missing']), (10, []), name)
        for mutation, label in P.LABELS.items():
            self.assertIn(label, read_json(self.out / f'sdf-detect-mutation{mutation}/result.json')['message'])

    def test_static_timing_is_clean_for_every_mutant_until_the_constraints_tell_the_truth(self):
        builds = read_json(self.out / 'builds.json')
        for mutation in range(4):
            timing = builds[f'sdf-m{mutation}']['preparation']['static_timing']
            self.assertGreaterEqual(min(timing['given_slack']['max'], timing['given_slack']['min']), 0, mutation)
            self.assertGreater(timing['need']['multicycle'] - P.SETUP, timing['period'], mutation)
            self.assertEqual(timing['given_slack']['audit'], int(mutation != 2))
            if mutation:
                self.assertLess(timing['corrected_slack'][P.CORRECTED[mutation]], 0, mutation)
        self.assertNotIn('static_timing', builds['gate-m0']['preparation'])

    def test_delays_and_limits_reach_the_simulation_only_in_the_sdf_view(self):
        builds = read_json(self.out / 'builds.json')
        self.assertIn('-gspecify', builds['sdf-m0']['command'])
        self.assertNotIn('-gspecify', builds['gate-m0']['command'])
        self.assertIn('defparam', (self.out / 'sdf-m0/mc_timing.v').read_text())
        self.assertNotIn('defparam', (self.out / 'gate-m0/mc_timing.v').read_text())
        self.assertIn('VIEW sdf', (self.out / 'sdf-boundaries/simulation.log').read_text())

    def test_each_mutant_fails_through_a_timing_violation_of_the_expected_flop(self):
        expected = {1: 'result_', 2: 'setup mc_tb.g_gate.dut.cfg_q_reg', 3: 'hold mc_tb.g_gate.dut.done_reg'}
        for mutation, text in expected.items():
            log = (self.out / f'sdf-detect-mutation{mutation}/simulation.log').read_text()
            violations = [line for line in log.splitlines() if line.startswith('TIMING ')]
            self.assertTrue(violations and all(text in line for line in violations), (mutation, violations[:3]))
        for case in ('sdf-boundaries', 'sdf-random-seed17'):
            self.assertNotIn('\nTIMING ', (self.out / case / 'simulation.log').read_text())

    def test_without_the_check_limits_the_hold_mutant_survives(self):
        # The path delays alone do not show mutant 3: the data changes after the late clock edge.
        timing = self.out / 'no-limits.v'
        timing.write_text('\n'.join(line for line in (self.out / 'sdf-m3/mc_timing.v').read_text().splitlines() if 'defparam' not in line)
                          .replace('../sdf-m3/', str(self.out / 'sdf-m3') + '/'))
        subprocess.run(['iverilog', '-g2012', '-s', 'mc_tb', '-Pmc_tb.GATE=2', '-Pmc_tb.MUTATION=3', *P.iverilog_options({'GATE': 2}),
                        '-o', str(self.out / 'no-limits.vvp'), str(self.out / 'sdf-m3/netlist.v'), str(P.CELLS), str(P.BENCH), str(timing)],
                       check=True, capture_output=True, timeout=60)
        output = subprocess.run(['vvp', str(self.out / 'no-limits.vvp'), f"+VECTORS={self.out / 'sdf-boundaries/vectors.txt'}",
                                 f"+WAVE={self.out / 'no-limits.vcd'}"], capture_output=True, text=True, timeout=60).stdout
        self.assertIn('RESULT PASS', output)


@unittest.skipUnless(TOOLS, 'Icarus, Yosys and OpenSTA required')
class FaultTests(unittest.TestCase):
    def test_each_mutant_as_the_design_fails_only_the_sdf_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in range(1, P.MUTANTS + 1):
                with self.subTest(fault=fault):
                    out = Path(tmp) / str(fault)
                    result = run(out, '--iterations', '2', '--demo-bug', str(fault), '--yosys', YOSYS, '--sta', STA)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(read_json(out / 'sdf-boundaries/result.json')['status'], 'fail')
                    self.assertEqual(read_json(out / 'gate-boundaries/result.json')['status'], 'pass')
                    self.assertEqual(read_json(out / 'rtl-boundaries/result.json')['status'], 'pass')

    def test_a_missing_timing_tool_fails_only_the_sdf_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run(out, '--iterations', '2', '--yosys', YOSYS, '--sta', str(Path(tmp) / 'absent'))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            results = {p.parent.name: read_json(p)['status'] for p in out.glob('*/result.json')}
            self.assertTrue(all(status == 'error' for name, status in results.items() if name.startswith('sdf-')))
            self.assertTrue(all(status == 'pass' for name, status in results.items() if not name.startswith('sdf-')))


if __name__ == '__main__':
    unittest.main()
