import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load('cdc_structural_run', HERE / 'run.py')
C, G = R.C, R.G
YOSYS = shutil.which('yowasp-yosys') or shutil.which('yosys')
TARGETS = {target['id']: target for target in R.load_targets()}
TWO = dict(clocks=['a_clk', 'b_clk'], inputs={'a_in': 'a_clk'}, outputs={'b_out': 'b_clk'})
HEAD = 'module t (input wire a_clk, b_clk, a_in, output wire b_out);\n    reg a_q;\n    always @(posedge a_clk) a_q <= a_in;\n'


def synthesize(text, top, parameters=None):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'design.sv').write_text(text)
        script = C.synthesis_script('design.sv', top, parameters or {}, 'netlist.json')
        subprocess.run([YOSYS, '-q', '-p', script], cwd=tmp, check=True, capture_output=True, text=True, timeout=120)
        return json.loads((Path(tmp) / 'netlist.json').read_text())


def keys(report):
    return [C.finding_key(finding) for finding in report['findings']]


def run(out, *options, timeout=300):
    return subprocess.run([sys.executable, str(HERE / 'run.py'), '--out', str(out), *options],
                          capture_output=True, text=True, timeout=timeout)


class WaiverTests(unittest.TestCase):
    FINDINGS = [dict(rule='NO_SYNC', sources=['a'], sinks=['b'], bits=8),
                dict(rule='RESET_RELEASE', sources=['rst_n'], sinks=['q'], bits=1)]
    HASHES = {'rtl/x.sv': 'abc'}

    def waiver(self, **changes):
        base = dict(id='W1', targets=['t'], disposition='waived', findings=['NO_SYNC a->b'], reason='held by the handshake',
                    review='read the RTL', expires=dict(condition='the source changes', source_sha256={'rtl/x.sv': 'abc'}))
        return dict(base, **changes)

    def test_valid_waiver_excuses_only_the_finding_it_names(self):
        excused, remaining, errors = C.apply_waivers('t', self.FINDINGS, [self.waiver()], self.HASHES)
        self.assertEqual(errors, [])
        self.assertEqual([(f['waiver'], f['disposition']) for f in excused], [('W1', 'waived')])
        self.assertEqual([C.finding_key(f) for f in remaining], ['RESET_RELEASE rst_n->q'])

    def test_waiver_of_another_target_is_not_applied(self):
        excused, remaining, errors = C.apply_waivers('other', self.FINDINGS, [self.waiver()], self.HASHES)
        self.assertEqual((excused, len(remaining), errors), ([], 2, []))

    def test_changed_or_missing_source_expires_the_waiver(self):
        for hashes in ({'rtl/x.sv': 'changed'}, {}):
            excused, remaining, errors = C.apply_waivers('t', self.FINDINGS, [self.waiver()], hashes)
            self.assertEqual((excused, len(remaining)), ([], 2))
            self.assertIn('expired', errors[0])

    def test_waiver_for_a_finding_that_is_gone_is_an_error(self):
        _, _, errors = C.apply_waivers('t', self.FINDINGS[1:], [self.waiver()], self.HASHES)
        self.assertEqual(len(errors), 1)
        self.assertIn('does not have', errors[0])

    def test_incomplete_waivers_are_rejected_and_excuse_nothing(self):
        broken = [self.waiver(reason=' '), self.waiver(review=''), self.waiver(disposition='ignored'),
                  self.waiver(expires=dict(condition='x', source_sha256={})), self.waiver(expires=dict(source_sha256={'rtl/x.sv': 'abc'})),
                  self.waiver(findings=[])]
        for waiver in broken:
            with self.subTest(waiver=waiver):
                excused, remaining, errors = C.apply_waivers('t', self.FINDINGS, [waiver], self.HASHES)
                self.assertEqual((excused, len(remaining), len(errors)), ([], 2, 1))

    def test_two_waivers_cannot_claim_one_finding(self):
        _, _, errors = C.apply_waivers('t', self.FINDINGS, [self.waiver(), self.waiver(id='W2')], self.HASHES)
        self.assertTrue(any('both list' in error for error in errors))

    def test_checked_in_waivers_name_real_targets_and_current_sources(self):
        waivers = R.read_json(R.WAIVERS)['waivers']
        self.assertEqual({w['disposition'] for w in waivers}, set(C.DISPOSITIONS))
        for waiver in waivers:
            self.assertLessEqual(set(waiver['targets']), set(TARGETS))
            for name, value in waiver['expires']['source_sha256'].items():
                self.assertEqual(C.sha256(ROOT / name), value, waiver['id'])


class GeneratorTests(unittest.TestCase):
    def test_seed_reproduction(self):
        self.assertEqual(G.generate(3, 12), G.generate(3, 12))
        self.assertNotEqual(G.generate(3, 12)['source'], G.generate(4, 12)['source'])

    def test_every_pattern_is_present_and_predicts_its_own_finding(self):
        rules = dict(no_sync='NO_SYNC', port='NO_SYNC', comb='COMB_BEFORE_SYNC', fanout='FANOUT_BEFORE_SYNC',
                     reconverge='RECONVERGENCE', multibit='MULTIBIT_SEPARATE_SYNC', reset='RESET_RELEASE')
        for seed in range(5):
            generated = G.generate(seed, 20)
            self.assertEqual(set(generated['kinds']), set(G.KINDS))
            self.assertEqual(sum(generated['kinds'].values()), 20)
            expected = {}
            for kind, count in generated['kinds'].items():
                if kind in rules:
                    expected[rules[kind]] = expected.get(rules[kind], 0) + count
            found = {}
            for finding in generated['expected']['findings']:
                found[finding['rule']] = found.get(finding['rule'], 0) + 1
            self.assertEqual(found, expected)
            self.assertRegex(generated['source'], r'g\d+ <= \{g\d+\[[\d:]+\], ~s\d+\};')

    def test_names_and_scripts(self):
        self.assertEqual([C.base_name(n) for n in ('rsync[1][2]', 'memory[3]', 'full', 's3a')], ['rsync', 'memory', 'full', 's3a'])
        script = C.synthesis_script('x.sv', 'top', dict(DEPTH=8, A=1), 'n.json')
        self.assertIn('chparam -set A 1 top; chparam -set DEPTH 8 top; hierarchy -check -top top', script)
        self.assertNotIn('opt_merge', script)   # merging equal flops would hide a signal sent to two synchronisers
        self.assertNotIn('abc', script)


@unittest.skipUnless(YOSYS, 'Yosys required')
class RuleTests(unittest.TestCase):
    def analyse(self, body, description=TWO, disabled=()):
        return C.analyze(synthesize(HEAD + body + 'endmodule\n', 't'), 't', description, disabled)

    def test_each_negative_example_reports_its_rule_alone_and_nothing_without_it(self):
        for target in TARGETS.values():
            if target['kind'] != 'negative':
                continue
            with self.subTest(target=target['id']):
                data = synthesize((ROOT / target['source']).read_text(), target['top'])
                self.assertEqual({f['rule'] for f in C.analyze(data, target['top'], target)['findings']}, {target['rule']})
                self.assertEqual(C.analyze(data, target['top'], target, disabled=[target['rule']])['findings'], [])
        self.assertEqual({t['rule'] for t in TARGETS.values() if t['kind'] == 'negative'}, set(C.RULES))

    def test_positive_example_is_clean_and_loses_that_with_one_reset_stage(self):
        target = TARGETS['good']
        text = (ROOT / target['source']).read_text()
        report = C.analyze(synthesize(text, target['top']), target['top'], target)
        self.assertEqual(report['findings'], [])
        self.assertEqual(len(report['synchronizers']), 3)
        self.assertEqual(report['asynchronous_reset_flops'], sum(report['flops'].values()))
        old = 'a_rst_meta <= 1\'b1; a_rst_n <= a_rst_meta;'
        self.assertIn(old, text)
        single = C.analyze(synthesize(text.replace(old, "a_rst_meta <= 1'b1; a_rst_n <= 1'b1;"), target['top']), target['top'], target)
        self.assertTrue(single['findings'])
        self.assertEqual({f['rule'] for f in single['findings']}, {'RESET_RELEASE'})
        self.assertTrue(all(f['sources'] == ['a_rst_n'] for f in single['findings']))

    def test_synchroniser_forms_that_are_accepted(self):
        for body in ('    reg [1:0] s;\n    always @(posedge b_clk) s <= {s[0], a_q};\n    assign b_out = s[1];\n',
                     '    reg [2:0] s;\n    always @(posedge b_clk) s <= {s[1:0], ~a_q};\n    assign b_out = ~s[2];\n',
                     '    reg [1:0] s;\n    always @(negedge b_clk) s <= {s[0], a_q};\n    assign b_out = s[1];\n'):
            with self.subTest(body=body):
                report = self.analyse(body)
                self.assertEqual(report['findings'], [])
                self.assertEqual([(s['source'], s['sink'], s['stages']) for s in report['synchronizers']],
                                 [('a_q', 's', 3 if '[2:0]' in body else 2)])

    def test_first_stage_that_is_used_or_gated_is_not_a_synchroniser(self):
        tapped = self.analyse('    reg [1:0] s;\n    always @(posedge b_clk) s <= {s[0], a_q};\n    assign b_out = s[1] & s[0];\n')
        self.assertEqual(keys(tapped), ['NO_SYNC a_q->s'])
        self.assertEqual(tapped['synchronizers'], [])
        enabled = self.analyse('    reg [1:0] s;\n    reg b_en;\n    always @(posedge b_clk) begin b_en <= ~b_en; if (b_en) s[0] <= a_q; s[1] <= s[0]; end\n'
                               '    assign b_out = s[1];\n')
        self.assertEqual(enabled['findings'], [])   # an enable of the receiving domain does not disturb the first stage
        foreign = self.analyse('    reg [1:0] s;\n    reg a_en;\n    always @(posedge a_clk) a_en <= ~a_in;\n'
                               '    always @(posedge b_clk) begin if (a_en) s[0] <= a_q; s[1] <= s[0]; end\n    assign b_out = s[1];\n')
        self.assertEqual(keys(foreign), ['COMB_BEFORE_SYNC a_en,a_q->s'])

    def test_one_bit_sent_twice_is_fanout_and_not_a_bus(self):
        target = TARGETS['fanout-before-sync']
        report = C.analyze(synthesize((ROOT / target['source']).read_text(), target['top']), target['top'], target)
        self.assertEqual(keys(report), ['FANOUT_BEFORE_SYNC a_q->b_enable_sync,b_start_sync'])
        self.assertEqual(len(report['synchronizers']), 2)

    def test_what_cannot_be_read_is_an_error(self):
        gated = HEAD + '    reg q;\n    wire g = b_clk & a_in;\n    always @(posedge g) q <= a_q;\n    assign b_out = q;\nendmodule\n'
        with self.assertRaisesRegex(C.Unsupported, 'not a declared clock'):
            C.analyze(synthesize(gated, 't'), 't', TWO)
        latch = HEAD + '    reg q;\n    always @* if (b_clk) q = a_q;\n    assign b_out = q;\nendmodule\n'
        with self.assertRaisesRegex(C.Unsupported, 'sequential cell'):
            C.analyze(synthesize(latch, 't'), 't', TWO)
        plain = synthesize(HEAD + '    assign b_out = a_q;\nendmodule\n', 't')
        self.assertEqual(keys(C.analyze(plain, 't', TWO)), ['NO_SYNC a_q->b_out'])
        for description, message in ((dict(TWO, inputs={}), 'no declared domain'), (dict(TWO, outputs={}), 'no declared domain'),
                                     (dict(TWO, inputs={'a_in': 'x_clk'}), 'unknown domain'),
                                     (dict(TWO, outputs={'b_out': 'x_clk'}), 'unknown domain'),
                                     (dict(TWO, inputs={'a_in': 'a_clk', 'ghost': 'a_clk'}), 'not in the netlist')):
            with self.subTest(message=message, description=description):
                with self.assertRaisesRegex(C.Unsupported, message):
                    C.analyze(plain, 't', description)
        with self.assertRaisesRegex(C.Unsupported, 'unknown rules'):
            C.analyze(plain, 't', TWO, disabled=['NO_SUCH_RULE'])
        with self.assertRaisesRegex(C.Unsupported, 'not in the netlist'):
            C.analyze(plain, 'other', TWO)

    def test_existing_examples_have_the_flops_their_declarations_give(self):
        ledger = R.read_json(R.LEDGER)['targets']
        # cdc_handshake: req 1 + data_reg 8 + ack_sync S + toggle 1; rst_sync S + req_sync S + ack 1 + pulse_sync S + pulse_prev 1
        for stages in (2, 3):
            self.assertEqual(ledger[f'cdc-handshake-sync{stages}']['flops'], dict(dst_clk=3 * stages + 2, src_clk=10 + stages))
        # async_fifo with A address bits: wbin, wgray A+1 each, full 1, rsync S*(A+1), memory 8*DEPTH; rbin, rgray, empty, rd_valid, rd_data 8, wsync
        for depth, stages, name in ((4, 2, 'async-fifo-depth4-sync2'), (8, 3, 'async-fifo-depth8-sync3')):
            width = depth.bit_length()
            self.assertEqual(ledger[name]['flops'], dict(rclk=2 * width + 10 + stages * width,
                                                         wclk=2 * width + 1 + stages * width + 8 * depth))
        self.assertEqual(ledger['irq-cdc-pending']['findings'], {})
        self.assertEqual(set(ledger), set(TARGETS))


@unittest.skipUnless(YOSYS, 'Yosys required')
class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / 'smoke'
        cls.result = run(cls.out, '--yosys', YOSYS)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_smoke_passes_with_every_planned_check_and_goal(self):
        self.assertEqual(self.result.returncode, 0, self.result.stdout + self.result.stderr)
        summary = json.loads((self.out / 'summary.json').read_text())
        manifest = json.loads((self.out / 'manifest.json').read_text())
        self.assertTrue(summary['success'] and summary['complete'])
        self.assertEqual(summary['planned'], 29)
        self.assertEqual([r['id'] for r in summary['results']], manifest['check_ids'])
        coverage = json.loads((self.out / 'coverage.json').read_text())
        self.assertEqual((coverage['hit'], coverage['required'], coverage['missing']), (28, 28, []))
        suite = ET.parse(self.out / 'junit.xml').getroot()
        self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')), ('29', '0', '0'))
        for name in ('examples/local-cdc-structural/ledger.json', 'examples/local-cdc-structural/waivers.json',
                     'examples/local-cdc-handshake/rtl/cdc_handshake.sv', 'examples/local-async-fifo/rtl/async_fifo.sv',
                     'examples/local-irq-cdc/rtl/cdc_receiver.sv', 'examples/local-cdc-structural/rtl/cdc_good.sv'):
            self.assertIn(name, manifest['source_sha256'])

    def test_evidence_is_accepted_by_the_regression_runner(self):
        regression = load('cdc_regression', ROOT / 'tools/run_regression.py')
        entry = dict(id='local-cdc-structural', script='examples/local-cdc-structural/run.py', kind='simulation',
                     profile=True, options=['timeout'], tools=['yowasp-yosys'])
        inspected = regression.inspect_output(self.out, entry, {entry['id']: entry}, profile='smoke')
        self.assertEqual(inspected['junit'], 29)

    def test_reports_keep_the_crossings_and_the_excused_findings(self):
        report = json.loads((self.out / 'async-fifo-depth4-sync2/report.json').read_text())
        self.assertEqual(report['problems'], [])
        self.assertEqual({row['disposition'] for row in report['excused']}, {'waived', 'known-debt'})
        self.assertEqual(len(report['excused']), 16)
        self.assertEqual(report['open'], [])
        self.assertTrue((self.out / 'async-fifo-depth4-sync2/netlist.json').is_file())
        crossings = json.loads((self.out / 'crossings.json').read_text())
        self.assertEqual(set(crossings), set(TARGETS))

    def test_checker_that_lost_a_rule_fails_the_normal_run(self):
        for number in (1, 6):
            with self.subTest(rule=C.RULES[number - 1]):
                out = Path(self.tmp.name) / f'demo{number}'
                result = run(out, '--yosys', YOSYS, '--demo-bug', str(number))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                summary = json.loads((out / 'summary.json').read_text())
                failed = {r['id'] for r in summary['results'] if r['status'] != 'pass'}
                self.assertFalse(summary['success'])
                self.assertIn('target-' + ('no-sync' if number == 1 else 'reset-release'), failed)
                self.assertIn('requirements-and-coverage', failed)

    def test_missing_tool_and_timeout_are_failures_not_detections(self):
        for label, options in (('missing', ['--yosys', str(Path(self.tmp.name) / 'no-such-yosys')]),
                               ('timeout', ['--yosys', YOSYS, '--timeout', '0.001'])):
            with self.subTest(label=label):
                out = Path(self.tmp.name) / label
                result = run(out, *options)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                summary = json.loads((out / 'summary.json').read_text())
                status = {r['id']: r['status'] for r in summary['results']}
                self.assertEqual(status['tool-version'], 'fail')
                self.assertEqual(status['target-good'], 'fail')
                self.assertEqual(status['checker-without-NO_SYNC'], 'fail')
                if label == 'timeout':   # a broken source that only timed out was not shown to be rejected
                    self.assertEqual(status['build-failure'], 'fail')
                self.assertEqual(summary['planned'], 29)

    def test_existing_output_and_bad_options_are_refused(self):
        self.assertEqual(run(self.out, '--yosys', YOSYS).returncode, 2)
        self.assertEqual(run(Path(self.tmp.name) / 'blocks', '--blocks', '3').returncode, 2)
        self.assertFalse((Path(self.tmp.name) / 'blocks').exists())


if __name__ == '__main__':
    unittest.main()
