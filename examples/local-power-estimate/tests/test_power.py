import copy
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, run_example

P = load_example('local-power-estimate')
M = P.MODEL
C = P.load_contract()
STA = Path(shutil.which('sta') or P.ROOT / 'artifacts/toolchains/opensta-build/sta')
TOOLS = STA.exists() and shutil.which('iverilog') and shutil.which('vvp')
VCD = '''$timescale 1ps $end
$scope module tb $end
$scope module dut $end
$var wire 1 ! clk $end
$var wire 2 " q [1:0] $end
$scope module r0 $end
$var wire 1 ! CLK $end
$upscope $end
$upscope $end
$scope module other $end
$var wire 1 # clk $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
$dumpvars
0!
b0 "
0#
$end
#5000
1!
1#
#10000
0!
b11 "
#15000
1!
#20000
0!
b10 "
'''
REPORT = '''BEGIN ANNOTATION
vcd            7
unannotated     0
END ANNOTATION
BEGIN INSTANCES
        Internal       Switching         Leakage           Total
           Power           Power           Power           Power (Watts)
----------------------------------------------------------------
 4.000000047e-07 9.999999975e-07 9.999999717e-10 1.400999963e-06 ckbuf
 1.107692214e-07 6.153845789e-08 3.999999887e-09 1.763076796e-07 r3
END INSTANCES
RESULT POWER DONE
'''


class ModelTests(unittest.TestCase):
    def test_transitions_skip_first_values_other_scopes_and_nested_pins(self):
        counts, duration = M.transitions(VCD, 'tb/dut')
        self.assertEqual(counts, {'clk': 4, 'q[1]': 1, 'q[0]': 2})
        self.assertEqual(duration, 20.0)
        self.assertEqual(M.transitions(VCD, 'tb/other')[0], {'clk': 1})
        with self.assertRaises(ValueError):
            M.transitions(VCD, 'tb/absent')
        with self.assertRaises(ValueError):       # unknown values are not silently counted
            M.transitions(VCD.replace('b11 "', 'bx1 "'), 'tb/dut')
        with self.assertRaises(ValueError):
            M.transitions(VCD.split('#5000')[0], 'tb/dut')

    def test_expected_power_of_one_flop_by_hand(self):
        module = M.parse_netlist('module one(input clk, input d, output q);\n DFF r(.CLK(clk),.D(d),.Q(q));\nendmodule\n')['one']
        self.assertEqual(M.pin_count(module), 6)
        power = M.expected_power(module, {'clk': 200, 'd': 30, 'q': 10}, 1000.0, C)['r']
        # clock pin 0.004 pJ x 0.2/ns, output 0.010 pJ x 0.01/ns; load 0.02 pF: half C V^2 x 0.01/ns
        self.assertAlmostEqual(power['internal'], 0.8e-6 + 0.1e-6, places=12)
        self.assertAlmostEqual(power['switching'], 0.5 * 0.02 * 0.01 * 1e-3, places=15)
        self.assertAlmostEqual(power['leakage'], 4e-9, places=15)
        with self.assertRaises(ValueError):
            M.expected_power(module, {'clk': 200, 'd': 30}, 1000.0, C)

    def test_netlists_have_the_structure_the_comparison_relies_on(self):
        modules = M.parse_netlist(P.NETLIST.read_text())
        self.assertEqual(set(modules), {'bank_plain', 'bank_gated', 'bank_stuck'})
        cells = lambda name: sorted(cell for cell, _ in modules[name]['instances'].values())
        self.assertEqual(cells('bank_plain'), ['BUF'] + ['DFF'] * 8 + ['MUX2'] * 8)
        self.assertEqual(cells('bank_gated'), ['BUF'] + ['DFF'] * 8 + ['ICG'])
        self.assertEqual(cells('bank_stuck'), ['BUF'] + ['DFF'] * 8 + ['ICG'] + ['MUX2'] * 8)
        self.assertEqual([M.pin_count(modules[n]) for n in ('bank_plain', 'bank_gated', 'bank_stuck')], [76, 47, 80])
        self.assertEqual(modules['bank_gated']['instances']['gate'][1]['EN'], 'en')
        self.assertEqual(modules['bank_stuck']['instances']['gate'][1]['EN'], 'bypass')

    def test_library_holds_the_energies_and_capacitances_of_the_contract(self):
        text = P.LIBRARY.read_text()
        for name, cell in C['cells'].items():
            block = text[text.index(f'cell({name})'):].split('\n cell(')[0]
            self.assertEqual(float(re.search(r'cell_leakage_power : ([\d.]+);', block).group(1)), cell['leakage_nw'])
            for pin, item in {**cell['inputs'], **cell['outputs']}.items():
                body = block[block.index(f'pin({pin})'):].split('\n  pin(')[0]
                if 'cap_pf' in item:
                    self.assertEqual(float(re.search(r'capacitance : ([\d.]+);', body).group(1)), item['cap_pf'])
                energies = set(map(float, re.findall(r'(?:rise|fall)_power\(scalar\) \{ values\("([\d.]+)"\)', body)))
                self.assertEqual(energies, {item['energy_pj']} if 'energy_pj' in item else set(), (name, pin))
        self.assertIn('default_operating_conditions : typical;', text)

    def test_stimulus_is_reproducible_and_loads_at_the_stated_rate(self):
        rows = M.stimulus(17, 320, 16)
        self.assertEqual(rows, M.stimulus(17, 320, 16))
        self.assertNotEqual(rows, M.stimulus(18, 320, 16))
        self.assertEqual([sum(r[0] for r in M.stimulus(17, 320, n)) for n in (16, 4, 1)], [20, 80, 320])
        self.assertTrue(all(row[2] == row[1] for row in rows if row[0]))


class JudgeTests(unittest.TestCase):
    def test_report_must_be_complete_and_unambiguous(self):
        annotation, power = P.parse_report(REPORT)
        self.assertEqual(annotation, dict(annotated=7, unannotated=0, other={}))
        self.assertEqual(set(power), {'ckbuf', 'r3'})
        for text in (REPORT.replace('RESULT POWER DONE\n', ''), REPORT.replace('END INSTANCES\n', ''),
                     REPORT.replace(' r3\n', ' ckbuf\n'),
                     REPORT.replace('unannotated     0\n', ''), re.sub(r'^ .*(ckbuf|r3)\n', '', REPORT, flags=re.M)):
            with self.assertRaises(ValueError):
                P.parse_report(text)
        self.assertEqual(P.parse_report(REPORT.replace('vcd            7\n', ''))[0]['annotated'], 0)

    def test_verdict_order_and_each_label(self):
        ok = dict(annotated=47, unannotated=0, other={})
        low, high = C['activities']['low']['saving'], C['activities']['high']['saving']
        self.assertEqual(P.derive(ok, 47, {}, 0.2, low), 'PASS')
        self.assertEqual(P.derive(ok, 47, {}, None, low), 'PASS')
        self.assertEqual(P.derive(dict(ok, annotated=0, unannotated=47), 47, {'r0': {}}, 2.0, low), 'POWER_ACTIVITY')
        self.assertEqual(P.derive(dict(ok, annotated=46, unannotated=1), 47, {}, 0.2, low), 'POWER_SCOPE')
        self.assertEqual(P.derive(ok, 48, {}, 0.2, low), 'POWER_SCOPE')
        self.assertEqual(P.derive(dict(ok, other={'input': 3}), 47, {}, 0.2, low), 'POWER_SCOPE')
        self.assertEqual(P.derive(ok, 47, {'r0': {'internal': 'high'}}, 2.0, low), 'POWER_VALUE')
        self.assertEqual(P.derive(ok, 47, {}, 0.36, low), 'POWER_SAVING')
        self.assertEqual(P.derive(ok, 47, {}, 0.79, high), 'POWER_SAVING')
        self.assertEqual(P.derive(ok, 47, {}, 1.07, high), 'PASS')

    def test_small_difference_is_reported_and_missing_instance_is_an_error(self):
        expected = {'r0': dict(internal=1e-6, switching=1e-7, leakage=4e-9)}
        close = {'r0': dict(internal=1.00005e-6, switching=1e-7, leakage=4e-9)}
        self.assertEqual(P.differing(close, expected, C['relative_tolerance']), {})
        off = {'r0': dict(internal=1.001e-6, switching=0.9e-7, leakage=4e-9)}
        self.assertEqual(P.differing(off, expected, C['relative_tolerance']), {'r0': {'internal': 'high', 'switching': 'low'}})
        with self.assertRaises(ValueError):
            P.differing({}, expected, C['relative_tolerance'])

    def test_detection_needs_the_planted_evidence(self):
        module = M.parse_netlist(P.NETLIST.read_text())['bank_gated']
        flops = {f'r{i}': {'internal': 'high'} for i in range(8)}
        ok = dict(annotated=47, unannotated=0, other={})
        self.assertTrue(P.intended(3, ok, flops, module))
        self.assertFalse(P.intended(3, ok, dict(flops, gate={'internal': 'high'}), module))
        self.assertFalse(P.intended(3, ok, {k: v for k, v in flops.items() if k != 'r7'}, module))
        self.assertTrue(P.intended(2, dict(ok, unannotated=1), flops, module))
        self.assertFalse(P.intended(2, dict(ok, unannotated=1), {}, module))
        self.assertFalse(P.intended(1, ok, {}, module))
        self.assertFalse(P.intended(4, ok, flops, module))

    def test_plan_and_malformed_contract(self):
        cases = P.make_cases(P.ACTIVITIES, 0, C)
        self.assertEqual(len(cases), 21)
        self.assertEqual(sum(c['category'] == 'mutation' for c in cases), 11)
        self.assertEqual([c['id'] for c in cases if c['category'] == 'diagnostic'], ['high-unseen-mutation4'])
        self.assertEqual(P.order_verdict(dict(low=0.2, mid=0.4, high=0.9))[0], 'pass')
        self.assertEqual(P.order_verdict(dict(low=0.5, mid=0.4, high=0.9))[0], 'fail')
        self.assertEqual(P.order_verdict(dict(low=0.2, mid=0.4))[0], 'error')
        changes = [lambda d: d['activities'].pop('mid'), lambda d: d['activities']['low'].update(saving={}),
                   lambda d: d.update(relative_tolerance=0.5), lambda d: d.update(cycles=4), lambda d: d['cells'].pop('ICG'),
                   lambda d: d['activities']['low'].update(load_every=0)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'contract.json'
            for change in changes:
                data = copy.deepcopy(C)
                change(data)
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    P.load_contract(path)


class RealToolTests(unittest.TestCase):
    @unittest.skipUnless(TOOLS, 'OpenSTA and Icarus Verilog required')
    def test_real_simulation_and_power_reports_for_all_activities(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            r = run_example('local-power-estimate', out, '--sta', os.path.relpath(STA))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            s = json.loads((out / 'summary.json').read_text())
            self.assertTrue(s['success'] and s['complete'] and s['evidence_ok'])
            self.assertEqual((s['planned'], len(s['results']), s['detected'], s['unseen']), (22, 22, 11, 1))
            j = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((j.get('tests'), j.get('errors'), j.get('failures')), ('23', '0', '0'))
            self.assertLess(s['ratios']['low'], s['ratios']['mid'])
            self.assertLess(s['ratios']['mid'], s['ratios']['high'])
            # Without the activity file the tool still prints watts: only the annotation count tells.
            blind = json.loads((out / 'low-detect-mutation1/result.json').read_text())
            self.assertEqual(blind['annotation']['annotated'], 0)
            self.assertGreater(blind['measured_total_w'], 0)
            gated = json.loads((out / 'low-gated/result.json').read_text())
            self.assertEqual((gated['annotation']['annotated'], gated['pins']), (47, 47))
            self.assertAlmostEqual(gated['measured_total_w'] / gated['expected_total_w'], 1, places=4)
            self.assertIn('$enddefinitions', (out / 'low-simulation/wave.vcd').read_text())

    @unittest.skipUnless(TOOLS, 'OpenSTA and Icarus Verilog required')
    def test_each_demo_fails_the_gated_analysis_and_seed_changes_the_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mutation in range(1, P.MUTANTS + 1):
                out = Path(tmp) / str(mutation)
                r = run_example('local-power-estimate', out, '--configuration', 'low', '--sta', str(STA), '--demo-bug', str(mutation))
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertEqual(json.loads((out / 'low-gated/result.json').read_text())['status'], 'fail')
            out = Path(tmp) / 'seed'
            r = run_example('local-power-estimate', out, '--configuration', 'low', '--sta', str(STA), '--seed', '18')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotEqual((out / 'low-simulation/vectors.txt').read_text(), (Path(tmp) / '1/low-simulation/vectors.txt').read_text())

    @unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus Verilog required')
    def test_missing_requested_tool_is_an_error_without_path_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            r = run_example('local-power-estimate', out, '--sta', str(Path(tmp) / 'absent'))
            self.assertEqual(r.returncode, 1)
            s = json.loads((out / 'summary.json').read_text())
            self.assertFalse(s['success'])
            self.assertFalse(s['evidence_ok'])
            self.assertTrue(all(row['status'] == 'error' for row in s['results'] if row['category'] not in ('simulation', 'comparison')))


if __name__ == '__main__':
    unittest.main()
