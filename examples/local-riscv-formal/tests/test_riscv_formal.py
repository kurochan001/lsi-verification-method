from argparse import Namespace
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

P = load_example('local-riscv-formal')
TOOLS = all(shutil.which(name) for name in ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'yowasp-yosys-witness', 'z3'))
ARGS = Namespace(sby='yowasp-sby', yosys='yowasp-yosys', smtbmc='yowasp-yosys-smtbmc', witness='yowasp-yosys-witness',
                 formal_timeout=300, timeout=30)


def by_id(profile='smoke', demo_bug=0):
    return {t['id']: t for t in P.plan(profile, demo_bug)}


class PlanTests(unittest.TestCase):
    def test_every_mutant_has_exactly_one_task_with_its_number(self):
        tasks = by_id()
        for number, (configuration, _parameters, failure) in P.MUTANTS.items():
            name = f"{configuration}-{'detect' if failure else 'invisible'}-mutation{number}"
            self.assertEqual(tasks[name]['parameters']['MUTATION'], number)
            self.assertEqual(tasks[name]['expect'], 'FAIL' if failure else 'PASS')
            self.assertEqual(tasks[name]['failure'], failure)
        mutated = [t for t in tasks.values() if t['parameters']['MUTATION']]
        self.assertEqual(len(mutated), len(P.MUTANTS))

    def test_expected_assertion_belongs_to_the_group_the_task_checks(self):
        for task in by_id().values():
            if task['failure']:
                self.assertIn(task['failure'], P.properties(None, task)['assert'], task['id'])

    def test_normal_tasks_check_the_original_core_and_cover_all_four_groups(self):
        normal = [t for t in by_id().values() if t['category'] == 'normal' and t['mode'] == 'bmc']
        self.assertTrue(all(t['parameters']['MUTATION'] == 0 for t in normal))
        checked = set()
        for task in normal:
            checked |= P.enabled(task)
        self.assertEqual(checked, set().union(*P.GROUPS.values()))
        classes = {t['parameters']['CLASS'] for t in normal if t['parameters']['CHECK'] == 1 and t['configuration'] == 'none'}
        self.assertEqual(classes, set(P.CLASSES))

    def test_demo_bug_reaches_only_the_normal_tasks(self):
        tasks = by_id(demo_bug=3)
        self.assertEqual(tasks['none-pc-chain']['parameters']['MUTATION'], 3)
        self.assertEqual(tasks['none-scenario-cover']['parameters']['MUTATION'], 0)
        self.assertEqual(tasks['none-detect-mutation1']['parameters']['MUTATION'], 1)

    def test_nightly_adds_tasks_and_depth_and_drops_none(self):
        smoke, nightly = by_id('smoke'), by_id('nightly')
        self.assertLess(set(smoke), set(nightly))
        self.assertIn('dynamic-result-shift', nightly)
        self.assertEqual(nightly['none-pc-chain']['depth'], smoke['none-pc-chain']['depth'] + 1)

    def test_every_requirement_goal_is_a_planned_task(self):
        catalog = json.loads(P.REQUIREMENTS.read_text())
        for profile in ('smoke', 'nightly'):
            tasks = P.plan(profile)
            records = [dict(id=t['id'], outcome='pass') for t in tasks]
            rows, unknown = P.audit_requirements(catalog, tasks, records)
            self.assertEqual(unknown, [])
            self.assertTrue(all(row['passed'] for row in rows))
        # nightly-only goals are judged when they are planned
        rows, _ = P.audit_requirements(catalog, P.plan('nightly'), [dict(id=t['id'], outcome='pass') for t in P.plan('smoke')])
        self.assertFalse(next(r for r in rows if r['id'] == 'RF-MEMORY')['passed'])

    def test_a_failed_or_missing_task_fails_its_requirement(self):
        catalog = json.loads(P.REQUIREMENTS.read_text())
        tasks = P.plan('smoke')
        records = [dict(id=t['id'], outcome='error' if t['id'] == 'none-pc-chain' else 'pass') for t in tasks if t['id'] != 'none-result-add']
        failed = {row['id'] for row in P.audit_requirements(catalog, tasks, records)[0] if not row['passed']}
        self.assertEqual(failed, {'RF-PC', 'RF-RESULT'})

    def test_harness_declares_every_assertion_cover_and_the_core_ports_by_name(self):
        text = P.HARNESS.read_text()
        for name in set().union(*P.GROUPS.values()) | P.COVERS | {'as_legal'}:
            self.assertEqual(text.count(name + ':'), 1, name)
        self.assertIn('.TRAPS(0)', text)
        self.assertNotIn('rv32i_core core (clk', text)


class VerdictTests(unittest.TestCase):
    CASE = dict(id='x', mode='bmc', expect='FAIL', depth=11, category='mutation', failure='ap_pc_chain')
    WANTED = {'assert': {'ap_pc_chain', 'ap_halt', 'ap_pc_first'}, 'assume': {'as_legal'}, 'cover': P.COVERS}

    def execution(self, returncode, error=None):
        return dict(error=error, returncode=returncode)

    def test_timeout_tool_error_or_other_assertion_is_not_a_detection(self):
        log = 'Assert failed in rvfi_formal: ap_pc_chain\n'
        self.assertEqual(P.judge(self.CASE, self.execution(2), 'FAIL', log, ['t.vcd'], self.WANTED)[0], 'detected')
        self.assertEqual(P.judge(self.CASE, self.execution(None, 'command timeout'), 'FAIL', log, ['t.vcd'], self.WANTED)[0], 'error')
        self.assertEqual(P.judge(self.CASE, self.execution(2), 'FAIL', 'Assert failed in rvfi_formal: ap_halt\n', ['t.vcd'], self.WANTED)[0], 'error')
        self.assertEqual(P.judge(self.CASE, self.execution(2), 'FAIL', log, [], self.WANTED)[0], 'error')
        self.assertEqual(P.judge(self.CASE, self.execution(16), 'ERROR', '', [], self.WANTED)[0], 'error')
        self.assertEqual(P.judge(self.CASE, self.execution(0), 'PASS', 'Status: passed\n', [], self.WANTED)[0], 'fail')

    def test_overconstrained_run_must_reach_nothing(self):
        case = dict(id='o', mode='cover', expect='FAIL', depth=16, category='diagnostic', failure=None)
        nothing = ''.join(f'Unreached cover statement at rvfi_formal: {name}\n' for name in P.COVERS)
        self.assertEqual(P.judge(case, self.execution(2), 'FAIL', nothing, [], self.WANTED)[0], 'detected')
        one = nothing.replace('Unreached cover statement at rvfi_formal: cp_lui\n', 'Reached cover statement in step 7 at rvfi_formal: cp_lui\n')
        self.assertNotEqual(one, nothing)
        self.assertEqual(P.judge(case, self.execution(2), 'FAIL', one, [], self.WANTED)[0], 'error')
        self.assertEqual(P.judge(case, self.execution(0), 'PASS', nothing, [], self.WANTED)[0], 'error')


@unittest.skipUnless(TOOLS, 'formal tools required')
class ToolTests(unittest.TestCase):
    def run_task(self, case, edit=None):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            harness = P.HARNESS
            if edit:
                old, new = edit
                text = P.HARNESS.read_text()
                self.assertEqual(text.count(old), 1)
                harness = out / P.HARNESS.name
                harness.write_text(text.replace(old, new))
            saved = P.SOURCES
            P.SOURCES = [*P.RTL, harness]
            try:
                return P.run_task(ARGS, out, case)
            finally:
                P.SOURCES = saved

    def test_link_results_pass_with_the_compiled_assertions_of_the_group(self):
        record = self.run_task(by_id()['none-result-link'])
        self.assertEqual(record['outcome'], 'pass', record['message'])
        self.assertEqual(record['inventory']['assert'], ['ap_rd_addr', 'ap_rd_value'])
        self.assertNotIn('cp_wait', record['inventory']['cover'])
        self.assertEqual(record['inventory']['assume'], ['as_legal'])

    def test_unforwarded_jalr_base_breaks_the_pc_chain(self):
        record = self.run_task(by_id()['none-detect-mutation3'])
        self.assertEqual(record['outcome'], 'detected', record['message'])
        self.assertTrue(record['traces'])

    def test_a_wrong_expectation_in_the_harness_is_reported_on_the_original_core(self):
        # The check is not empty: with AUIPC expected to add 8 more, the unchanged core fails it.
        case = dict(by_id()['none-result-link'], expect='FAIL', category='mutation', failure='ap_rd_value')
        record = self.run_task(case, ("is_auipc ? rvfi_pc_rdata + imm_u :", "is_auipc ? rvfi_pc_rdata + imm_u + 32'd8 :"))
        self.assertEqual(record['outcome'], 'detected', record['message'])

    def test_a_model_without_a_planned_assertion_is_an_error_not_a_pass(self):
        record = self.run_task(by_id()['none-result-link'], ("            if (in_class && spec_value_known && rvfi_rd_addr != 5'd0) ap_rd_value: assert(rvfi_rd_wdata == spec_rd_wdata);\n", ""))
        self.assertEqual(record['outcome'], 'error')
        self.assertIn('inventory', record['message'])


if __name__ == '__main__':
    unittest.main()
