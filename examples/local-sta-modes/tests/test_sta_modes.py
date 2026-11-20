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

P = load_example('local-sta-modes')
C = P.load_contract()
STA = Path(shutil.which('sta') or P.ROOT / 'artifacts/toolchains/opensta-build/sta')
OK = dict(error=None, returncode=0)


def evidence(configuration, contract=C):
    """The log of a clean analysis, written from the contract."""
    mode = configuration.split('-')[0]
    lines = ['AUDIT constraints 1']
    for name in contract['paths']:
        pair = contract['expected'][configuration].get(name)
        for kind, index in (('max', 0), ('min', 1)):
            lines.append(f'MEASURE {name} {kind} {pair[index]}' if pair else f'MISSING {name} {kind}')
    lines += [f"CROSSING {name} {int(mode in item['exists_in'])}" for name, item in contract['crossings'].items()]
    return '\n'.join(lines + [f"RESULT STA DONE records={2 * len(contract['paths'])}"]) + '\n'


def case(configuration='func-slow', mutation=0, expect='PASS', category='normal'):
    mode, corner = configuration.split('-')
    return dict(configuration=configuration, mode=mode, corner=corner, mutation=mutation, expect=expect, category=category)


class ContractTests(unittest.TestCase):
    def test_expected_slacks_follow_from_the_cell_delays(self):
        for configuration, table in C['expected'].items():
            mode, corner = configuration.split('-')
            for name, pair in table.items():
                self.assertEqual(P.slack_pair(C, mode, corner, name), pair, (configuration, name))
        # Two values worked by hand in the README.
        self.assertEqual(C['expected']['func-slow']['logic'], [0.05, 1.39])
        self.assertEqual(C['expected']['scan-fast']['link01'], [9.55, 0.09])

    def test_library_files_hold_the_delays_of_the_contract(self):
        for corner, delay in C['corners'].items():
            text = (P.HERE / f'design/{corner}.lib').read_text()
            cell = lambda name: text[text.index(f'cell({name})'):].split('\n cell(')[0]
            first = lambda block, kind: float(re.search(kind + r'\(\w+\) \{[^}]*values\("([\d.]+),', block).group(1))
            self.assertEqual(first(cell('BUF'), 'cell_rise'), delay['BUF'])
            self.assertEqual(first(cell('MUX2'), 'cell_rise'), delay['MUX2'])
            self.assertEqual(first(cell('DFF'), 'cell_rise'), delay['clk_to_q'])
            setup, hold = cell('DFF').split('hold_rising')
            self.assertEqual(first(setup, 'rise_constraint'), delay['setup'])
            self.assertEqual(first(hold, 'rise_constraint'), delay['hold'])
            self.assertEqual(len(set(re.findall(r'cell_(?:rise|fall)\(delays\) \{[^}]*values\("([^)]*)\)', cell('MUX2')))), 1)

    def test_malformed_contract_cannot_remove_golden_checks(self):
        changes = [lambda d: d['expected']['func-slow'].pop('logic'),
                   lambda d: d['expected']['scan-fast'].update(link01=[9.55, float('nan')]),
                   lambda d: d['expected'].pop('scan-slow'),
                   lambda d: d['corners'].pop('fast'),
                   lambda d: d['crossings'].pop('cross_in'),
                   lambda d: d['paths']['logic'].update(timed_in=['func', 'scan']) or d['paths']['in'].update(timed_in=[]) or d['paths']['stage'].update(timed_in=[]),
                   lambda d: d.update(revision=0)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'contract.json'
            for change in changes:
                data = copy.deepcopy(C)
                change(data)
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    P.load_contract(path)

    def test_each_mistake_is_assigned_to_the_analyses_that_can_see_it(self):
        table = {m: [P.expected_label(m, mode, corner) for mode in P.MODES for corner in P.CORNERS] for m in range(1, P.MUTANTS + 1)}
        self.assertEqual(table[1], ['STA_SETUP', 'PASS', 'STA_SETUP', 'PASS'])      # setup: slow only
        self.assertEqual(table[2], ['PASS', 'PASS', 'PASS', 'STA_HOLD'])            # hold: scan mode, fast only
        self.assertEqual(table[5], ['STA_ASYNC', 'STA_ASYNC', 'PASS', 'PASS'])
        for mutation, label in ((3, 'STA_MODE'), (4, 'STA_PATH'), (6, 'STA_ASYNC')):
            self.assertEqual(table[mutation], [label] * 4)
        cases = P.make_cases(P.CONFIGS, 0)
        self.assertEqual(len(cases), 28)
        self.assertEqual(sum(c['category'] == 'mutation' for c in cases), 17)
        self.assertEqual(sum(c['category'] == 'diagnostic' for c in cases), 7)
        self.assertEqual(len({c['id'] for c in cases}), 28)


class JudgeTests(unittest.TestCase):
    def status(self, log, **changes):
        return P.judge(case(**changes), OK, log, C)[0]

    def test_clean_evidence_passes_in_every_configuration(self):
        for configuration in P.CONFIGS:
            self.assertEqual(self.status(evidence(configuration), configuration=configuration), 'pass')

    def test_missing_duplicate_or_nonfinite_records_are_errors(self):
        log = evidence('func-slow')
        for text in (log.replace('MEASURE logic max 0.05\n', ''), log.replace('RESULT STA DONE records=26', ''),
                     log + 'MEASURE logic max 0.05\n', log.replace('MEASURE logic max 0.05', 'MEASURE logic max NaN'),
                     log.replace('CROSSING cross_in 1\n', ''), log.replace('AUDIT constraints 1\n', '')):
            self.assertEqual(self.status(text), 'error')

    def test_positive_but_wrong_slack_and_a_vanished_crossing_fail(self):
        log = evidence('func-slow')
        self.assertEqual(self.status(log.replace('MEASURE logic max 0.05', 'MEASURE logic max 0.06')), 'fail')
        self.assertEqual(self.status(log.replace('CROSSING cross_in 1', 'CROSSING cross_in 0')), 'fail')

    def test_crash_or_tool_error_is_never_a_detection(self):
        mutant = dict(mutation=1, expect='STA_SETUP', category='mutation')
        self.assertEqual(P.judge(case(**mutant), dict(error=None, returncode=2), 'TOOL_ERROR x\n', C)[0], 'error')
        self.assertEqual(P.judge(case(**mutant), OK, 'Error: invalid liberty\n', C)[0], 'error')
        self.assertEqual(P.judge(case(**mutant), dict(error='command timeout', returncode=None), '', C)[0], 'error')

    def test_label_from_a_different_path_is_not_the_intended_detection(self):
        log = evidence('func-slow')
        # A setup violation, but on the output path instead of the long functional path.
        other = log.replace('MEASURE out max 0.85', 'MEASURE out max -0.1')
        self.assertEqual(self.status(other, mutation=1, expect='STA_SETUP', category='mutation'), 'error')
        # Only one of the three functional paths vanished: not the inverted case analysis.
        partial = log.replace('MEASURE logic max 0.05', 'MISSING logic max').replace('MEASURE logic min 1.39', 'MISSING logic min')
        self.assertEqual(self.status(partial, mutation=4, expect='STA_PATH', category='mutation'), 'error')
        # The enable path leaked but met timing: in the functional mode the false violation is part of the evidence.
        leaked = log.replace('MISSING enable max', 'MEASURE enable max 0.2').replace('MISSING enable min', 'MEASURE enable min 0.2')
        self.assertEqual(self.status(leaked, mutation=3, expect='STA_MODE', category='mutation'), 'error')
        self.assertEqual(self.status(leaked.replace('enable max 0.2', 'enable max -0.45'), mutation=3, expect='STA_MODE', category='mutation'), 'detected')

    def test_verdict_priority_and_survivors(self):
        log = evidence('func-slow')
        both = log.replace('MISSING cross_in max', 'MEASURE cross_in max -0.65').replace('MISSING cross_in min', 'MEASURE cross_in min 0.19')
        self.assertEqual(self.status(both, mutation=5, expect='STA_ASYNC', category='mutation'), 'detected')
        self.assertEqual(self.status(both.replace('AUDIT constraints 1', 'AUDIT constraints 0'), mutation=5, expect='STA_ASYNC', category='mutation'), 'fail')
        self.assertEqual(self.status(log, mutation=5, expect='STA_ASYNC', category='mutation'), 'fail')  # survived
        self.assertEqual(self.status(both, mutation=2, expect='PASS', category='diagnostic'), 'fail')     # unseen must be clean

    def test_corner_comparison_needs_both_corners_and_the_expected_order(self):
        slow = {'logic/max': 0.05, 'logic/min': 1.39}
        fast = {'logic/max': 1.35, 'logic/min': 0.29}
        self.assertEqual(P.corner_verdict('func', dict(slow=slow, fast=fast))[0], 'pass')
        self.assertEqual(P.corner_verdict('func', dict(slow=fast, fast=slow))[0], 'fail')
        self.assertEqual(P.corner_verdict('func', dict(slow=slow))[0], 'error')
        self.assertEqual(P.corner_verdict('func', dict(slow=slow, fast={'logic/max': 1.35}))[0], 'error')


class RealStaTests(unittest.TestCase):
    @unittest.skipUnless(STA.exists(), 'build OpenSTA as described in examples/local-sta/README.md')
    def test_real_sta_two_modes_two_corners_and_all_negative_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            r = run_example('local-sta-modes', out, '--sta', os.path.relpath(STA))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            s = json.loads((out / 'summary.json').read_text())
            self.assertTrue(s['success'] and s['complete'] and s['evidence_ok'])
            self.assertEqual((s['planned'], len(s['results']), s['detected'], s['unseen']), (30, 30, 17, 7))
            j = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((j.get('tests'), j.get('errors'), j.get('failures')), ('31', '0', '0'))
            leak = json.loads((out / 'func-slow-detect-mutation3/result.json').read_text())
            self.assertAlmostEqual(leak['slacks']['enable/max'], -0.45, places=4)
            half = json.loads((out / 'func-fast-detect-mutation5/result.json').read_text())
            self.assertNotIn('cross_out/max', half['slacks'])
            self.assertIn('cross_in/max', half['slacks'])
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(manifest['check_ids'], [row['id'] for row in s['results']])

    @unittest.skipUnless(STA.exists(), 'build OpenSTA as described in examples/local-sta/README.md')
    def test_demo_bugs_fail_the_normal_case_where_the_analysis_can_see_them(self):
        visible = {1: 'func-slow', 2: 'scan-fast', 3: 'func-fast', 4: 'scan-slow', 5: 'func-slow', 6: 'scan-fast'}
        with tempfile.TemporaryDirectory() as tmp:
            for mutation, configuration in visible.items():
                out = Path(tmp) / str(mutation)
                r = run_example('local-sta-modes', out, '--configuration', configuration, '--sta', str(STA), '--demo-bug', str(mutation))
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertEqual(json.loads((out / f'{configuration}-normal/result.json').read_text())['status'], 'fail')
            # One corner alone has no comparison between corners, and says so in its plan.
            self.assertEqual(json.loads((Path(tmp) / '1/manifest.json').read_text())['comparisons'], [])

    def test_missing_requested_tool_is_an_error_without_path_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            r = run_example('local-sta-modes', out, '--sta', str(Path(tmp) / 'absent'))
            self.assertEqual(r.returncode, 1)
            s = json.loads((out / 'summary.json').read_text())
            self.assertFalse(s['success'])
            self.assertFalse(s['evidence_ok'])
            self.assertTrue(all(row['status'] == 'error' for row in s['results']))


if __name__ == '__main__':
    unittest.main()
