from pathlib import Path
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json

P = load_example('local-coverage-unreachable')
DATA = P.load_items()
FORMAL = all(shutil.which(name) for name in ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'yowasp-yosys-witness', 'z3'))
VERILATOR = shutil.which('verilator')
VERSIONS = dict(yosys='0.70', z3='4.15.3', verilator='5.052')


def fresh_results():
    """What a correct run finds, built from the pinned classes without running a tool."""
    implicit = P.implicit_assumptions(DATA)
    results = {}
    for item in DATA['items']:
        proved = item['expected'] in P.EXCLUDABLE
        results[item['id']] = {'class': item['expected'], 'proof_task': 'prove-' + item['id'] if item['expected'] != 'reachable' else None,
                               'assumptions': sorted(implicit + item['assumptions']), 'helpers': sorted(item['helpers']) if proved or item['helpers'] else [],
                               'point_id': None}
    return results


def audit(ledger, fresh=None, versions=VERSIONS):
    fresh = fresh or fresh_results()
    for entry in P.json.loads(P.LEDGER.read_text())['exclusions']:      # measured points as the checked-in ledger records them
        if 'point_id' in entry:
            fresh[entry['item']]['point_id'] = entry['point_id']
    hashes = {name: P.sha256(P.ROOT / target['source']) for name, target in DATA['targets'].items()}
    return P.audit(ledger, DATA, fresh, hashes, versions)


def record(mode, status, code, **log):
    base = dict(reached=[], unreached=[], failed=[], induction=False, basecase_passed=False, induction_failed=False, bounded_passed=False)
    task = P.make_task(DATA, 't', 'guarded-unit', mode, 8, [('cover' if mode == 'cover' else 'never', 'target', 'state==DENY')], [])
    inventory = dict(**{'assert': task['asserts']}, assume=task['assumptions'], cover=task['covers'])
    return task, dict(error=None, formal_status=status, returncode=code, log=dict(base, **log), traces=['trace0.vcd'], inventory=inventory)


class ClassificationTests(unittest.TestCase):
    def test_only_a_trace_or_a_finished_induction_decides(self):
        self.assertEqual(P.classify('reached'), 'reachable')
        self.assertEqual(P.classify('unreached', 'proved'), 'unreachable')
        for prove in (None, 'inconclusive', 'bounded-pass'):
            self.assertEqual(P.classify('unreached', prove), 'unclassified', prove)

    def test_assumptions_need_the_required_behaviour_to_stay_reachable(self):
        self.assertEqual(P.classify('unreached', 'proved', ['as_functional_mode'], True), 'conditional')
        self.assertEqual(P.classify('unreached', 'proved', ['as_always_permitted'], False), 'invalid')
        self.assertEqual(P.classify('unreached', 'proved', ['as_functional_mode'], None), 'error')

    def test_errors_and_contradictions_are_never_a_class(self):
        self.assertEqual(P.classify('error', 'proved'), 'error')
        self.assertEqual(P.classify('unreached', 'error'), 'error')
        self.assertEqual(P.classify('unreached', 'refuted'), 'error')
        self.assertEqual(P.classify('reached', 'proved'), 'error')

    def test_task_outcomes_follow_status_exit_code_and_log_together(self):
        self.assertEqual(P.outcome(*record('cover', 'PASS', 0, reached=['target']))[0], 'reached')
        self.assertEqual(P.outcome(*record('cover', 'FAIL', 2, unreached=['target']))[0], 'unreached')
        self.assertEqual(P.outcome(*record('prove', 'PASS', 0, induction=True))[0], 'proved')
        self.assertEqual(P.outcome(*record('prove', 'UNKNOWN', 4, basecase_passed=True, induction_failed=True))[0], 'inconclusive')
        self.assertEqual(P.outcome(*record('prove', 'FAIL', 2, failed=['target']))[0], 'refuted')
        self.assertEqual(P.outcome(*record('bmc', 'PASS', 0, bounded_passed=True))[0], 'bounded-pass')

    def test_timeouts_tool_errors_and_partial_evidence_are_errors(self):
        task, rec = record('cover', 'FAIL', 2, unreached=['target'])
        self.assertEqual(P.outcome(task, dict(rec, error='command timeout'))[0], 'error')
        self.assertEqual(P.outcome(task, dict(rec, formal_status='TIMEOUT'))[0], 'error')
        self.assertEqual(P.outcome(task, dict(rec, formal_status='ERROR', returncode=16))[0], 'error')
        self.assertEqual(P.outcome(task, dict(rec, log=dict(rec['log'], unreached=[])))[0], 'error')      # FAIL without the unreached cover
        task, rec = record('prove', 'PASS', 0)                                                           # PASS without the induction line
        self.assertEqual(P.outcome(task, rec)[0], 'error')
        task, rec = record('prove', 'UNKNOWN', 4, basecase_passed=True)
        self.assertEqual(P.outcome(task, rec)[0], 'error')
        task, rec = record('cover', 'PASS', 0, reached=['target'])
        self.assertEqual(P.outcome(task, dict(rec, traces=[]))[0], 'error')

    def test_a_dropped_or_added_assumption_in_the_compiled_model_is_an_error(self):
        task, rec = record('prove', 'PASS', 0, induction=True)
        for assume in ([], ['as_initial_reset', 'as_always_permitted']):
            self.assertEqual(P.outcome(task, dict(rec, inventory=dict(rec['inventory'], assume=assume)))[0], 'error')


class PlanTests(unittest.TestCase):
    def test_item_table_pins_one_class_per_item(self):
        expected = [item['expected'] for item in DATA['items']]
        self.assertEqual({name: expected.count(name) for name in P.CLASSES},
                         dict(reachable=10, unreachable=3, conditional=1, unclassified=2, invalid=1))
        self.assertEqual(sum(item['category'] == 'measured' for item in DATA['items']), 10)

    def test_plan_is_fixed_and_nightly_adds_the_cross_checks(self):
        tasks, checks = P.plan_tasks(DATA, 'smoke')
        self.assertEqual((len(tasks), len(checks), len(set(checks))), (27, 42, 42))
        nightly_tasks, nightly = P.plan_tasks(DATA, 'nightly')
        self.assertEqual((len(nightly_tasks), len(nightly)), (37, 52))
        self.assertEqual(sum(name.startswith('cross-') for name in nightly), 10)
        self.assertNotIn('prove-gu-deny', tasks)          # a reached item needs no proof
        self.assertEqual(tasks['prove-gu-guard']['asserts'], ['ah_held_in_range', 'target'])
        self.assertEqual(tasks['prove-gu-guard-no-helper']['asserts'], ['target'])

    def test_every_task_carries_the_reset_assumption_and_only_declared_ones(self):
        tasks, _ = P.plan_tasks(DATA, 'nightly')
        for task in tasks.values():
            self.assertIn('as_initial_reset', task['assumptions'])
        self.assertEqual(tasks['prove-gu-test']['assumptions'], ['as_functional_mode', 'as_initial_reset'])
        self.assertEqual(tasks['cover-gu-deny']['assumptions'], ['as_initial_reset'])
        with self.assertRaises(ValueError):
            P.make_task(DATA, 'x', 'guarded-unit', 'cover', 8, [('cover', 'target', '1'), ('cover', 'target', '0')], [])
        with self.assertRaises(ValueError):
            P.make_task(DATA, 'x', 'guarded-unit', 'simulate', 8, [('cover', 'target', '1')], [])

    def test_harness_adds_checks_to_a_copy_and_keeps_the_source(self):
        source = P.GUARDED.read_text()
        text = P.harness(source, DATA, [('never', 'target', 'state==DENY'), ('helper', 'ah_held_in_range', 'held<LIMIT')], ['as_initial_reset', 'as_functional_mode'])
        self.assertTrue(text.startswith(source[:source.rindex('endmodule')]))
        for expected in ('target:assert(!(state==DENY));', 'ah_held_in_range:assert(held<LIMIT);', 'as_functional_mode:assume(!test_mode);',
                         'if(!f_past)as_initial_reset:assume(!rst_n);'):
            self.assertIn(expected, text)
        self.assertEqual(text.count('endmodule'), 1)
        self.assertEqual(P.GUARDED.read_text(), source)

    def test_item_table_rejects_malformed_entries(self):
        def broken(change):
            data = copy.deepcopy(json.loads(P.ITEMS.read_text()))
            change(data)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'items.json'
                path.write_text(json.dumps(data))
                with self.assertRaises((ValueError, KeyError)):
                    P.load_items(path)
        broken(lambda d: d['items'].append(copy.deepcopy(d['items'][0])))                      # duplicate id
        broken(lambda d: d['items'][0].update(expected='excluded'))                            # unknown class
        broken(lambda d: d['items'][0].update(assumptions=['as_unknown']))                     # undeclared assumption
        broken(lambda d: d['items'][-1].update(point=dict(t='line', l='1')))                   # a point on the unmeasured target
        broken(lambda d: d['assumptions']['as_functional_mode'].update(source=' '))            # assumption without a source

    def test_requirements_own_every_check_and_every_goal_names_a_check(self):
        requirements = json.loads(P.REQUIREMENTS.read_text())
        _, checks = P.plan_tasks(DATA, 'smoke')
        rows = P.requirement_coverage(requirements, checks, set(checks), 'smoke')
        self.assertEqual([row['id'] for row in rows if not row['applicable']], ['UR-CROSS'])
        self.assertTrue(all(row['passed'] for row in rows if row['applicable']))
        rows = P.requirement_coverage(requirements, checks, set(checks) - {'replay-cu-line-l24'}, 'smoke')
        self.assertEqual([row['id'] for row in rows if row['applicable'] and not row['passed']], ['UR-REPLAY'])
        with self.assertRaisesRegex(ValueError, 'without a requirement'):
            P.requirement_coverage(requirements, checks + ['unplanned-extra'], set(), 'smoke')
        with self.assertRaisesRegex(ValueError, 'without a planned check'):
            P.requirement_coverage(requirements, [name for name in checks if name != 'tools'], set(), 'smoke')


class WitnessTests(unittest.TestCase):
    WITNESS = dict(format='Yosys Witness Trace', signals=[
        dict(path=['\\a'], width=8, offset=0, init_only=False), dict(path=['\\authorized'], width=1, offset=0, init_only=False),
        dict(path=['\\b'], width=8, offset=0, init_only=False), dict(path=['\\enable'], width=1, offset=0, init_only=False),
        dict(path=['\\operation'], width=1, offset=0, init_only=False), dict(path=['\\req_valid'], width=1, offset=0, init_only=False),
        dict(path=['\\resp_ready'], width=1, offset=0, init_only=False), dict(path=['\\rst_n'], width=1, offset=0, init_only=False),
        dict(path=['\\state'], width=2, offset=0, init_only=True)])

    def bits(self, rst_n, req_valid, a=0, b=0, enable=0, authorized=0, operation=0, resp_ready=0, state=None):
        fields = [(a, 8), (authorized, 1), (b, 8), (enable, 1), (operation, 1), (req_valid, 1), (resp_ready, 1), (rst_n, 1)]
        if state is not None:
            fields.append((state, 2))
        return ''.join(format(value, f'0{width}b') for value, width in reversed(fields))

    def test_inputs_are_read_per_step_and_initial_state_is_left_out(self):
        steps = [dict(bits=self.bits(0, 0, state=3)), dict(bits=self.bits(1, 1, a=0x81, b=2, enable=1)), dict(bits=self.bits(1, 0)), dict(bits=self.bits(1, 0))]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'trace.yw'
            path.write_text(json.dumps(dict(self.WITNESS, steps=steps)))
            decoded = P.decode_witness(path)
            self.assertEqual(decoded[1], dict(a=0x81, authorized=0, b=2, enable=1, operation=0, req_valid=1, resp_ready=0, rst_n=1))
            self.assertNotIn('state', decoded[0])
            rows = P.replay_rows(decoded)
            # enable without authorization: the independent model expects a denied response with error and zero data
            self.assertEqual(len(rows), len(steps) + 3)
            # resp_ready is low in the last step of the trace, so the response is held for one more cycle
            self.assertEqual([(row[9], row[10], row[11]) for row in rows if row[9]], [(1, 0, 1), (1, 0, 1)])
            path.write_text(json.dumps(dict(self.WITNESS, steps=[dict(bits='1' + steps[1]['bits'])])))
            with self.assertRaises(ValueError):
                P.decode_witness(path)
            path.write_text(json.dumps(dict(self.WITNESS, steps=[])))
            with self.assertRaises(ValueError):
                P.decode_witness(path)

    def test_unhit_points_and_items_must_be_one_to_one(self):
        items = [dict(id='x', point=dict(t='line', l='24')), dict(id='y', point=dict(t='branch', l='25', o='else'))]
        points = [json.dumps(dict(t='line', l='24', n='9')), json.dumps(dict(t='branch', l='25', o='else'))]
        self.assertEqual(P.match_points(points, items), dict(x=points[0], y=points[1]))
        with self.assertRaisesRegex(ValueError, 'matches 0'):
            P.match_points(points[:1], items)
        with self.assertRaisesRegex(ValueError, 'one to one'):       # an unhit point that no item explains
            P.match_points(points + [json.dumps(dict(t='line', l='26'))], items)
        with self.assertRaisesRegex(ValueError, 'matches 2'):
            P.match_points(points + [json.dumps(dict(t='line', l='24', n='10'))], items)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.ledger = json.loads(P.LEDGER.read_text())

    def test_checked_in_ledger_matches_the_item_table(self):
        self.assertEqual(audit(self.ledger), [])
        self.assertEqual(sorted(entry['item'] for entry in self.ledger['exclusions']),
                         sorted(item['id'] for item in DATA['items'] if item['expected'] in P.EXCLUDABLE))
        for entry in self.ledger['exclusions']:
            self.assertIn('as_initial_reset', entry['assumptions'])
            self.assertEqual(entry['proof']['mode'], 'prove')

    def test_each_tampered_ledger_is_rejected_for_its_own_reason(self):
        for name, (_, code) in P.TAMPERINGS.items():
            with self.subTest(name=name):
                self.assertIn(code, audit(P.tampered(self.ledger, DATA, name)))
        self.assertEqual(audit(self.ledger), [])                      # tampering works on a copy

    def test_changed_expression_tool_version_or_missing_review_is_rejected(self):
        changed = copy.deepcopy(self.ledger); changed['exclusions'][0]['expression_sha256'] = 'f' * 64
        self.assertEqual(audit(changed), ['LEDGER_STALE_EXPRESSION'])
        self.assertEqual(audit(self.ledger, versions=dict(VERSIONS, yosys='0.71')), ['LEDGER_TOOL_VERSION'])
        self.assertEqual(audit(self.ledger, versions=dict(VERSIONS, z3=None)), ['LEDGER_TOOL_VERSION'])
        changed = copy.deepcopy(self.ledger); changed['exclusions'][1]['reason'] = ''
        self.assertEqual(audit(changed), ['LEDGER_NO_REVIEW'])
        changed = copy.deepcopy(self.ledger); del changed['exclusions'][2]['assumptions']
        self.assertEqual(audit(changed), ['LEDGER_ASSUMPTIONS'])
        changed = copy.deepcopy(self.ledger); changed['exclusions'][2]['helpers'] = []
        self.assertEqual(audit(changed), ['LEDGER_HELPERS'])
        changed = copy.deepcopy(self.ledger); changed['exclusions'].append(copy.deepcopy(changed['exclusions'][0]))
        self.assertEqual(audit(changed), ['LEDGER_UNKNOWN_ITEM'])
        self.assertEqual(audit(dict(schema_version=1, exclusions=[])), ['LEDGER_FORMAT'])

    def test_a_proof_that_no_longer_holds_invalidates_its_entry(self):
        for cls, code in (('reachable', 'LEDGER_REACHABLE'), ('unclassified', 'LEDGER_BOUNDED_ONLY'), ('invalid', 'LEDGER_OVERCONSTRAINED'), ('error', 'LEDGER_NO_PROOF')):
            fresh = fresh_results(); fresh['gu-guard']['class'] = cls
            self.assertEqual(audit(self.ledger, fresh), [code], cls)


@unittest.skipUnless(FORMAL, 'YoWASP Yosys, SBY and Z3 required')
class FormalToolTests(unittest.TestCase):
    def run_tasks(self, names):
        tasks, _ = P.plan_tasks(DATA, 'smoke')
        args = SimpleNamespace(sby=shutil.which('yowasp-sby'), yosys=shutil.which('yowasp-yosys'), smtbmc=shutil.which('yowasp-yosys-smtbmc'),
                               witness=shutil.which('yowasp-yosys-witness'), formal_timeout=120)
        with tempfile.TemporaryDirectory() as tmp:
            return {name: P.run_task(args, DATA, tasks[name], Path(tmp)) for name in names}

    def test_a_bounded_miss_and_a_bounded_pass_stay_unclassified_until_the_deeper_trace(self):
        records = self.run_tasks(['cover-gu-stall-shallow', 'bmc-gu-stall-shallow', 'prove-gu-stall-shallow', 'cover-gu-stall'])
        self.assertEqual({name: record['outcome'] for name, record in records.items()},
                         {'cover-gu-stall-shallow': 'unreached', 'bmc-gu-stall-shallow': 'bounded-pass',
                          'prove-gu-stall-shallow': 'inconclusive', 'cover-gu-stall': 'reached'})
        self.assertEqual(P.classify('unreached', 'bounded-pass'), 'unclassified')
        self.assertEqual(records['cover-gu-stall']['inventory']['assume'], ['as_initial_reset'])

    def test_an_assumption_that_blocks_required_behaviour_is_seen_in_the_goals(self):
        records = self.run_tasks(['prove-gu-deny-overconstrained', 'goals-as_always_permitted'])
        self.assertEqual(records['prove-gu-deny-overconstrained']['outcome'], 'proved')
        self.assertEqual((records['goals-as_always_permitted']['outcome'], records['goals-as_always_permitted']['log']['unreached']), ('unreached', ['g_deny']))


@unittest.skipUnless(FORMAL and VERILATOR, 'Verilator, YoWASP Yosys, SBY and Z3 required')
class RunnerTests(unittest.TestCase):
    def run_example(self, out, *options):
        return subprocess.run([sys.executable, str(P.HERE / 'run.py'), '--out', str(out), *options], capture_output=True, text=True, timeout=300)

    def test_real_run_classifies_replays_and_accepts_the_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = self.run_example(out)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            self.assertTrue(summary['success'] and summary['complete'])
            self.assertEqual((summary['planned'], len(summary['results'])), (42, 42))
            counts = read_json(out / 'classification.json')['counts']
            self.assertEqual(counts, dict(reachable=10, unreachable=3, conditional=1, unclassified=2, invalid=1, error=0))
            replays = sorted(out.glob('replay-*/coverage.dat'))
            self.assertEqual(len(replays), 8)
            self.assertEqual(len(list(out.glob('tasks/cover-*/reach-inputs.json'))), 10)
            self.assertEqual(read_json(out / 'ledger-audit.json')['problems'], [])
            self.assertFalse(self.run_example(out).returncode == 0)                 # an existing output is not overwritten
            # A ledger that also excludes a reachable item is rejected by the audit of the same results.
            fresh = read_json(out / 'classification.json')['items']
            audit_record = read_json(out / 'ledger-audit.json')
            bad = P.tampered(json.loads(P.LEDGER.read_text()), DATA, 'reachable')
            self.assertIn('LEDGER_REACHABLE', P.audit(bad, DATA, fresh, audit_record['source_sha256'], audit_record['tools']))
            self.assertEqual(P.audit(json.loads(P.LEDGER.read_text()), DATA, fresh, audit_record['source_sha256'], audit_record['tools']), [])


if __name__ == '__main__':
    unittest.main()
