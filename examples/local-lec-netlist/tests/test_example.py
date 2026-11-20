from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import EXAMPLES, load_example, read_json

P = load_example('local-lec-netlist')
N = P.N
YOSYS = shutil.which('yowasp-yosys') or shutil.which('yosys')
NAMES = {'alarm': {'alarm', 'warn'}, 'count[0]': {'count[0]', 'level[0]'}, 'state[1]': {'state[1]'}}
DONE = 'LEC_EQUIV_DONE\nLEC_BMC_DONE\n'
NO_MODEL = 'SAT proof finished - no model found: SUCCESS!\n'
MODEL = 'SAT proof finished - model found: FAIL!\n'


def tiny():
    """Two plain flops a and b behind one inverter; b is also the output q."""
    cell = lambda kind, **pins: dict(hide_name=0, type=kind, parameters={}, attributes={},
                                     connections={k: [v] for k, v in pins.items()})
    net = lambda *bits: dict(hide_name=0, bits=list(bits), attributes={})
    return dict(modules=dict(top=dict(
        ports=dict(clk=dict(direction='input', bits=[2]), d=dict(direction='input', bits=[3]),
                   q=dict(direction='output', bits=[6])),
        cells=dict(inv=cell('$_NOT_', A=3, Y=4), fa=cell('$_DFF_P_', C=2, D=4, Q=5), fb=cell('$_DFF_P_', C=2, D=5, Q=6)),
        netnames=dict(clk=net(2), d=net(3), a=net(5), b=net(6), q=net(6)))))


def status(proven, unproven):
    lines = [f'  Unproven $equiv $auto$1: \\u.{name}_gold{bit} \\u.{name}_gate{bit}\n' for name, bit in unproven]
    tail = '  Equivalence successfully proven!\n' if not unproven else ''
    return f' Of those cells {proven} are proven and {len(unproven)} are unproven.\n' + ''.join(lines) + tail


class NetlistTests(unittest.TestCase):
    def test_flops_are_named_after_the_internal_net_not_the_port(self):
        self.assertEqual(N.flops(tiny()['modules']['top']), {'a': 'fa', 'b': 'fb'})

    def test_scan_insertion_adds_one_multiplexer_per_flop_and_chains_them(self):
        scanned, chain = N.scan_insert(tiny(), 'top')
        module = scanned['modules']['top']
        self.assertEqual(chain, ['a', 'b'])
        self.assertEqual({k: v['direction'] for k, v in module['ports'].items() if k.startswith('scan')},
                         dict(scan_en='input', scan_in='input', scan_out='output'))
        first, second = module['cells']['scan_mux0']['connections'], module['cells']['scan_mux1']['connections']
        scan_en, scan_in = module['ports']['scan_en']['bits'][0], module['ports']['scan_in']['bits'][0]
        self.assertEqual((first['A'], first['B'], first['S']), ([4], [scan_in], [scan_en]))
        self.assertEqual((second['A'], second['B']), ([5], [5]))  # functional data of b is a; so is its scan data
        self.assertEqual(module['cells']['fa']['connections']['D'], first['Y'])
        self.assertEqual(module['ports']['scan_out']['bits'], [6])
        self.assertEqual(tiny()['modules']['top']['cells']['fa']['connections']['D'], [4])  # the input is not edited

    def test_deliberate_scan_errors_change_one_multiplexer(self):
        good = N.scan_insert(tiny(), 'top')[0]['modules']['top']['cells']
        swapped = N.scan_insert(tiny(), 'top', miswire='a')[0]['modules']['top']['cells']
        broken = N.scan_insert(tiny(), 'top', break_at='b')[0]['modules']['top']['cells']
        self.assertEqual(swapped['scan_mux0']['connections']['A'], good['scan_mux0']['connections']['B'])
        self.assertEqual(swapped['scan_mux1'], good['scan_mux1'])
        self.assertEqual(broken['scan_mux1']['connections']['B'], good['scan_mux0']['connections']['B'])
        self.assertEqual(broken['scan_mux0'], good['scan_mux0'])
        for bad in (dict(miswire='c'), dict(break_at='a')):
            with self.assertRaises(ValueError):
                N.scan_insert(tiny(), 'top', **bad)

    def test_scan_insertion_and_reset_mutation_reject_unexpected_flops(self):
        design = tiny()
        design['modules']['top']['cells']['fa']['type'] = '$_SDFF_PN0_'
        with self.assertRaises(ValueError):
            N.scan_insert(design, 'top')
        self.assertEqual(N.mutate_reset(design, 'top', 'a', 'polarity')['modules']['top']['cells']['fa']['type'], '$_SDFF_PP0_')
        self.assertEqual(N.mutate_reset(design, 'top', 'a', 'value')['modules']['top']['cells']['fa']['type'], '$_SDFF_PN1_')
        with self.assertRaises(ValueError):
            N.mutate_reset(design, 'top', 'b', 'polarity')  # b has no reset to change

    def test_compared_points_are_the_gold_nets_that_feed_equiv_cells(self):
        design = dict(modules=dict(equiv=dict(
            cells=dict(e1={'type': '$equiv', 'connections': dict(A=[2], B=[3], Y=[4])},
                       g={'type': '$_AND_', 'connections': dict(A=[5], B=[6], Y=[7])}),
            netnames={'u.count_gold': dict(bits=[9, 2]), 'u.count_gate': dict(bits=[8, 3]), 'u.idle_gold': dict(bits=[5])})))
        self.assertEqual(N.compared_points(design), {'u.count[1]'})


class JudgeTests(unittest.TestCase):
    def judge(self, differs, log, compared=None, trace=False, **task):
        required = {'u.' + alias for group in NAMES.values() for alias in group}
        return P.judge_equiv(dict(differs=differs, **task), log, required if compared is None else compared, NAMES, trace)[:2]

    def test_proof_needs_the_status_line_no_counterexample_and_the_compared_flops(self):
        good = status(5, []) + NO_MODEL + DONE
        self.assertTrue(self.judge([], good)[0])
        self.assertFalse(self.judge([], status(5, []) + MODEL + DONE, trace=True)[0])
        self.assertFalse(self.judge([], good, compared={'u.alarm', 'u.warn'})[0])  # most flops were never compared
        self.assertFalse(self.judge([], good.replace('  Equivalence successfully proven!\n', ''))[0])
        self.assertFalse(self.judge([], status(5, []) + NO_MODEL + 'LEC_EQUIV_DONE\n')[0])  # the bounded check never ran

    def test_difference_must_be_at_the_planned_points_with_a_counterexample(self):
        at_alarm = status(3, [('alarm', ''), ('warn', '')]).replace('\\u.warn_gold \\u.warn_gate', '\\warn_gold \\warn_gate')
        at_alarm += '  Unproven $equiv $auto$2: \\u.warn_gold \\u.warn_gate\n'
        at_alarm = at_alarm.replace('2 are unproven', '3 are unproven')
        self.assertEqual(P.unproven_points(at_alarm), {'u.alarm', 'u.warn', 'warn'})
        self.assertTrue(self.judge(['alarm'], at_alarm + MODEL + DONE, trace=True)[0])
        self.assertFalse(self.judge(['alarm'], at_alarm + MODEL + DONE, trace=False)[0])     # no waveform
        self.assertFalse(self.judge(['alarm'], at_alarm + NO_MODEL + DONE, trace=True)[0])   # unreachable from reset
        self.assertFalse(self.judge(['count[0]'], at_alarm + MODEL + DONE, trace=True)[0])   # another flop
        self.assertFalse(self.judge([], at_alarm + MODEL + DONE, trace=True)[0])             # a difference that was not planned

    def test_bit_of_a_bus_and_outputs_computed_from_a_flop(self):
        log = status(2, [('count', ' [0]'), ('level', ' [0]')]) + '  Unproven $equiv $auto$3: \\level_gold [0] \\level_gate [0]\n'
        log = log.replace('2 are unproven', '3 are unproven')
        self.assertTrue(self.judge(['count[0]'], log + MODEL + DONE, trace=True)[0])
        self.assertEqual(P.expected_points(['state[1]'], ['busy'], NAMES), {'u.state[1]', 'u.busy', 'busy'})

    def test_tool_error_or_ambiguous_log_is_never_a_detection(self):
        at_alarm = status(3, [('alarm', '')])
        self.assertFalse(self.judge(['alarm'], 'ERROR: something\n' + at_alarm + MODEL + DONE, trace=True)[0])
        self.assertFalse(self.judge(['alarm'], at_alarm + MODEL + NO_MODEL + DONE, trace=True)[0])
        self.assertFalse(self.judge(['alarm'], '', trace=True)[0])
        self.assertIsNone(P.bmc_verdict(MODEL))  # the script did not reach its end
        self.assertFalse(P.judge_shift(dict(counterexample=True), 'ERROR: x\n' + MODEL + 'LEC_BMC_DONE\n', True)[0])
        self.assertFalse(P.judge_shift(dict(counterexample=True), NO_MODEL + 'LEC_BMC_DONE\n', False)[0])
        self.assertFalse(P.judge_shift(dict(counterexample=False), MODEL + 'LEC_BMC_DONE\n', True)[0])
        self.assertTrue(P.judge_shift(dict(counterexample=False), NO_MODEL + 'LEC_BMC_DONE\n', False)[0])

    def test_dropped_output_must_not_be_compared(self):
        kept = {'u.count[0]', 'u.level[0]', 'u.state[1]'}
        good = status(3, []) + NO_MODEL + DONE
        self.assertTrue(self.judge([], good, compared=kept, drop=['warn'])[0])
        self.assertFalse(self.judge([], good, compared=kept | {'u.alarm'}, drop=['warn'])[0])

    def test_plan_and_catalog_name_the_same_tasks(self):
        _, goals = P.E.C.catalog(P.HERE / 'requirements.json')
        ids = [task['id'] for task in P.TASKS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(goals, set(ids))
        self.assertEqual(sum(bool(t.get('differs')) or t.get('counterexample', False) for t in P.TASKS), 7)

    def test_wrappers_have_the_same_ports_and_tie_or_pass_scan_enable(self):
        gold, gate = P.wrappers(dict(gold=12, scan='tied'))
        self.assertEqual(gold.split(');')[0].replace('gold', ''), gate.split(');')[0].replace('gate', ''))
        self.assertIn(".scan_en(1'b0)", gate)
        self.assertIn('.scan_en(scan_en)', P.wrappers(dict(gold=12, scan='free'))[1])
        self.assertNotIn('scan', P.wrappers(dict(gold=10))[1])
        self.assertIn('.warn()', P.wrappers(dict(gold=10, drop=['warn']))[0])


@unittest.skipUnless(YOSYS, 'Yosys required')
class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.args = SimpleNamespace(yosys=YOSYS, timeout=120)
        cls.designs, cls.chain, cls.names = P.build(cls.args, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def task(self, name, **task):
        return P.run_task(self.args, self.out, dict(id=name, kind='equiv', gold=P.OLD_ALARM, **task), self.designs, self.chain, self.names)

    def test_synthesis_keeps_eight_named_flops_and_exports_every_netlist(self):
        self.assertEqual(len(self.chain), 8)
        self.assertEqual(self.names['alarm'], {'alarm', 'warn'})
        record = read_json(self.out / 'netlists/netlists.json')
        for name in self.designs:
            self.assertIn(f'{name}.v', record['sha256'])
            self.assertIn(f'module {P.NET}', (self.out / f'netlists/{name}.v').read_text())
        self.assertIn('scan_out', (self.out / 'netlists/scan.v').read_text())
        self.assertNotIn('scan_out', (self.out / 'netlists/synth.v').read_text())

    def test_wrong_plans_are_rejected_on_the_real_tool(self):
        # a real difference that the plan calls equivalent
        self.assertFalse(self.task('unplanned-difference', gate='reset-polarity', differs=[])[0])
        # an equivalent netlist that the plan calls different
        self.assertFalse(self.task('missing-difference', gate='synth', differs=['alarm'])[0])
        # the difference is real, but at another flop than the plan says
        self.assertFalse(self.task('other-flop', gate='reset-value', differs=['alarm'])[0])
        # without the outputs computed from the flop, the plan is incomplete
        self.assertFalse(self.task('no-outputs', gate='scan-miswire', scan='tied', differs=['state[1]'])[0])

    def test_kept_range_needs_the_changed_output_dropped(self):
        # Dropping an output that other flops do not depend on proves the rest; the old RTL against the
        # ECO netlist with nothing dropped does not.
        self.assertTrue(self.task('kept', gate='eco', drop=['warn'], differs=[])[0])
        self.assertFalse(self.task('all', gate='eco', differs=[])[0])

    def test_missing_tool_is_an_error_not_a_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = subprocess.run([sys.executable, str(EXAMPLES / 'local-lec-netlist/run.py'), '--out', str(out),
                                     '--yosys', str(Path(tmp) / 'no-such-yosys')], capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertFalse(summary['success'])
            self.assertTrue(all(r['status'] == 'fail' for r in summary['results'] if r['id'] != 'inputs-unchanged'))

    def test_full_run_passes_with_every_planned_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = subprocess.run([sys.executable, str(EXAMPLES / 'local-lec-netlist/run.py'), '--out', str(out),
                                     '--yosys', YOSYS], capture_output=True, text=True, timeout=300)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary, manifest = read_json(out / 'summary.json'), read_json(out / 'manifest.json')
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual(summary['planned'], 16)
            self.assertEqual([r['id'] for r in summary['results']], manifest['check_ids'])
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), ('16', '0', '0'))
            for task in P.TASKS:
                record = read_json(out / task['id'] / 'result.json')
                self.assertTrue(record['ok'], record)
                wants_trace = bool(task.get('differs')) or task.get('counterexample', False)
                self.assertEqual((out / task['id'] / 'counterexample.vcd').exists(), wants_trace, task['id'])
            diagnosis = read_json(out / 'diagnose-scan-unconstrained/result.json')
            self.assertTrue({'u.' + flop for flop in self.chain} <= set(diagnosis['unproven']))


if __name__ == '__main__':
    unittest.main()
