import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

P = load_example('local-register-formal')
G = P.load('register_formal_generator', P.GENERATOR)
BINDINGS = json.loads(P.BINDINGS.read_text())
TOOLS = all(shutil.which(name) for name in ('yowasp-sby', 'yowasp-yosys', 'yowasp-yosys-smtbmc', 'yowasp-yosys-witness', 'z3'))
WIDE = P.HERE / 'registers.rdl'
SPEC = P.SPEC / 'registers.rdl'


def table(configuration, bug=0):
    source = WIDE if configuration == 'wide' else SPEC
    return P.flatten(G.build(G.fields_of(source), BINDINGS[configuration], bug))


class PlanTests(unittest.TestCase):
    def test_every_mutant_has_one_task_that_expects_an_assertion_of_the_hand_written_table(self):
        tasks = {t['id']: t for t in P.plan('smoke')}
        for block, mutants in P.MUTANTS.items():
            names = P.expected_table(block)['asserts']
            for number, failure in mutants.items():
                task = tasks[f'{block}-detect-mutation{number}']
                self.assertEqual((task['parameters']['MUTATION'], task['expect'], task['failures']), (number, 'FAIL', [failure]))
                self.assertIn(failure, names)
        self.assertEqual(sum(t['category'] == 'mutation' for t in tasks.values()), 11)

    def test_nightly_adds_the_block_with_wait_cycles_and_nothing_else(self):
        smoke = {t['id'] for t in P.plan('smoke')}
        nightly = {t['id']: t for t in P.plan('nightly')}
        added = set(nightly) - smoke
        self.assertEqual(added, {'spec-wait2-prove', 'spec-wait2-cover', *[f'spec-wait2-detect-mutation{n}' for n in (1, 2, 3)]})
        self.assertTrue(all(nightly[name]['parameters']['WAIT_CYCLES'] == 2 for name in added))
        self.assertTrue(smoke <= set(nightly))

    def test_normal_proofs_use_the_original_blocks_unless_a_demo_bug_is_asked_for(self):
        self.assertTrue(all(t['parameters']['MUTATION'] == 0 for t in P.plan('smoke') if t['category'] == 'normal'))
        mutated = {t['id'] for t in P.plan('smoke', 2) if t['category'] == 'normal' and t['parameters']['MUTATION'] == 2}
        self.assertEqual(mutated, {'spec-prove', 'wide-prove'})

    def test_every_generator_bug_has_a_table_check_and_a_proof_task(self):
        ids = P.check_ids(P.plan('smoke'), P.variants('smoke'))
        self.assertEqual(len(ids), len(set(ids)))
        for bug, row in P.GENERATOR_BUGS.items():
            self.assertIn(f'generator-bug{bug}-table-rejects', ids)
            self.assertIn(f"generator-bug{bug}-proof-{'still-passes' if row['proof'] == 'PASS' else 'fails'}", ids)
        self.assertEqual(set(P.GENERATOR_BUGS), set(G.DEMO_BUGS))

    def test_requirement_goals_are_planned_checks_in_both_profiles(self):
        catalog = json.loads(P.REQUIREMENTS.read_text())
        for profile in ('smoke', 'nightly'):
            ids = set(P.check_ids(P.plan(profile), P.variants(profile)))
            rows, unknown = P.audit_requirements(catalog, ids, ids)
            self.assertEqual(unknown, [], profile)
            self.assertTrue(all(row['passed'] for row in rows))
        smoke_ids = set(P.check_ids(P.plan('smoke'), P.variants('smoke')))
        rows, _unknown = P.audit_requirements(catalog, smoke_ids, smoke_ids)
        self.assertFalse(any(g.startswith('spec-wait2') for row in rows for g in row['goals']))

    def test_a_failed_or_unknown_goal_fails_its_requirement(self):
        catalog = dict(requirements=[dict(id='A', goals=['x', 'nightly:y']), dict(id='B', goals=['z'])])
        rows, unknown = P.audit_requirements(catalog, {'x', 'y'}, {'x'})
        self.assertEqual([(r['id'], r['passed']) for r in rows], [('A', False), ('B', False)])
        self.assertEqual(unknown, ['z'])
        rows, unknown = P.audit_requirements(catalog, {'x', 'z'}, {'x', 'z'})
        self.assertEqual(([r['passed'] for r in rows], unknown), ([True, True], []))


class GeneratorTests(unittest.TestCase):
    def test_generated_tables_equal_the_hand_written_ones(self):
        for name in ('spec', 'wide'):
            self.assertEqual(P.differences(table(name), P.expected_table(name)), [], name)

    def test_each_planted_generator_error_changes_the_wide_table(self):
        expected = P.expected_table('wide')
        changed = {bug: {row['name'] for row in P.differences(table('wide', bug), expected)} for bug in G.DEMO_BUGS}
        self.assertEqual(changed[1], {'ap_ctrl_reserved', 'ap_status_reserved'})
        self.assertIn('ap_status_done_w1c', changed[2])
        self.assertIn('ap_status_done_write', changed[2])
        self.assertEqual(changed[3], {'ap_ctrl_mode_reset', 'ap_ctrl_rev_reset', 'ap_ctrl_rev_const', 'ap_id_value_reset', 'ap_id_value_const'})
        self.assertEqual(changed[4], {'ap_unmapped_error', 'ap_unmapped_read', 'covers'})
        self.assertEqual(changed[5], {'ap_ctrl_reserved', 'ap_status_reserved'})

    def test_the_simple_map_cannot_show_the_reserved_mask_error(self):
        self.assertEqual(P.differences(table('spec', 5), P.expected_table('spec')), [])
        self.assertNotEqual(P.differences(table('spec', 1), P.expected_table('spec')), [])

    def test_table_comparison_notices_value_position_missing_and_extra_rows(self):
        expected = P.expected_table('wide')
        for change in ('reset', 'lsb', 'missing', 'extra', 'cover', 'assume'):
            wrong = copy.deepcopy(expected)
            if change == 'reset':
                wrong['asserts']['ap_ctrl_mode_reset'][4] = '0x4'
            elif change == 'lsb':
                wrong['asserts']['ap_ctrl_mode_write'][2] = 0
            elif change == 'missing':
                del wrong['asserts']['ap_id_ro_write']
            elif change == 'extra':
                wrong['asserts']['ap_new'] = ['hold', 0, 0, 1, None]
            elif change == 'cover':
                wrong['covers'] = wrong['covers'][1:]
            else:
                wrong['assumes'] = [*wrong['assumes'], 'as_idle']
            with self.subTest(change=change):
                self.assertEqual(len(P.differences(wrong, expected)), 1)

    def test_text_has_one_named_statement_per_row_with_the_constants_of_the_table(self):
        registers = G.fields_of(WIDE)
        rows = G.build(registers, BINDINGS['wide'])
        text = G.text(registers, rows, BINDINGS['wide'])
        for name in [a['name'] for a in rows['asserts']] + rows['covers'] + rows['assumes']:
            self.assertEqual(text.count(f' {name}: '), 1, name)
        for fragment in ("ctrl_mode == 3'h5", '$past(pwdata[6:4])', "(prdata & 32'hfffff08e) == 32'd0", "paddr == 8'd12",
                         'events[2:1]', 'ap_id_ro_write: assert(!pslverr)', "id_value == 32'h57494445"):
            self.assertIn(fragment, text)
        self.assertNotIn('as_idle', text)
        self.assertEqual(G.text(registers, rows, BINDINGS['wide'], idle=True).count('as_idle: assume(!psel);'), 1)
        spec = G.fields_of(SPEC)
        self.assertIn('ap_idreg_ro_write: assert(pslverr)', G.text(spec, G.build(spec, BINDINGS['spec']), BINDINGS['spec']))

    def test_unsupported_descriptions_are_rejected_instead_of_read_loosely(self):
        source = WIDE.read_text()
        changes = [('sw=rw;hw=r;reset=3\'h5;', 'sw=rw;hw=rw;reset=3\'h5;'), ('precedence=hw;reset=1\'b0;', 'reset=1\'b0;'),
                   ('stickybit;precedence=hw;reset=2\'h0;', 'precedence=hw;reset=2\'h0;'), ('sw=r;hw=r;reset=4\'h9;', 'sw=r;hw=r;'),
                   ('sw=rw;hw=r;reset=1\'b0;', 'sw=rw;hw=r;onread=rclr;reset=1\'b0;'), ('} limit @ 0x8;', '} limit[2] @ 0x10;'),
                   ('} id @ 0xc;', '} id @ 0x100;')]
        with tempfile.TemporaryDirectory() as tmp:
            for index, (before, after) in enumerate(changes):
                with self.subTest(change=after):
                    self.assertIn(before, source)
                    path = Path(tmp) / f'bad{index}.rdl'
                    path.write_text(source.replace(before, after))
                    with self.assertRaises(ValueError):
                        G.fields_of(path)

    def test_contract_of_the_spec_example_is_compared_field_by_field(self):
        model = G.fields_of(SPEC)
        contract = json.loads((P.SPEC / 'contract.json').read_text())
        self.assertTrue(P.same_contract(model, contract))
        wrong = copy.deepcopy(contract)
        wrong[0]['reset'] += 1
        self.assertFalse(P.same_contract(model, wrong))
        self.assertFalse(P.same_contract(G.fields_of(WIDE), contract))


class EvidenceTests(unittest.TestCase):
    def test_properties_go_in_front_of_the_only_endmodule(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.sv'
            path.write_text('module a;\nwire x;\nendmodule\n')
            self.assertEqual(P.formal_source(path), 'module a;\nwire x;\n`include "properties.svh"\nendmodule\n')
            path.write_text('module a;endmodule\nmodule b;endmodule\n')
            with self.assertRaises(ValueError):
                P.formal_source(path)
        self.assertNotIn('properties.svh', P.WIDE_RTL.read_text())

    def test_any_listed_assertion_confirms_a_planned_failure_and_an_unlisted_one_does_not(self):
        wanted = {'assert': {'ap_a', 'ap_b', 'ap_c'}, 'assume': set(), 'cover': set()}
        execution = dict(error=None, returncode=2)
        case = dict(category='counterexample', mode='prove', expect='FAIL', failures=['ap_a', 'ap_b'])
        log = 'Assert failed in top: ap_b\n'
        self.assertEqual(P.judge(case, execution, 'FAIL', log, ['t.vcd'], wanted)[0], 'detected')
        self.assertEqual(P.judge(case, execution, 'FAIL', 'Assert failed in top: ap_c\n', ['t.vcd'], wanted)[0], 'error')
        self.assertEqual(P.judge(case, execution, 'FAIL', log, [], wanted)[0], 'error')
        self.assertEqual(P.judge(case, dict(error=None, returncode=0), 'PASS', 'successful proof by k-induction', [], wanted)[0], 'fail')

    def test_idle_environment_must_leave_exactly_the_transfer_goals_unreached(self):
        wanted = {'assert': set(), 'assume': set(), 'cover': {'cp_s_event', 'cp_s_clear', 'cp_s_read'}}
        case = dict(category='diagnostic', mode='cover', expect='FAIL', failures=[])
        execution = dict(error=None, returncode=2)
        reached = 'Reached cover statement in step 2 at top: cp_s_event\n'
        rest = 'Unreached cover statement at top: cp_s_clear\nUnreached cover statement at top: cp_s_read\n'
        self.assertEqual(P.judge(case, execution, 'FAIL', reached + rest, [], wanted)[0], 'detected')
        self.assertEqual(P.judge(case, execution, 'FAIL', rest, [], wanted)[0], 'error')
        also = reached + 'Reached cover statement in step 4 at top: cp_s_read\nUnreached cover statement at top: cp_s_clear\n'
        self.assertEqual(P.judge(case, execution, 'FAIL', also, [], wanted)[0], 'error')
        self.assertEqual(P.judge(case, dict(error='command timeout', returncode=None), 'FAIL', reached + rest, [], wanted)[0], 'error')


@unittest.skipUnless(TOOLS, 'formal tools required')
class RunTests(unittest.TestCase):
    def run_example(self, out, *options):
        return subprocess.run([sys.executable, str(P.HERE / 'run.py'), '--out', str(out), *options], capture_output=True, text=True)

    def test_smoke_passes_with_every_planned_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = self.run_example(out)
            self.assertEqual(result.returncode, 0, result.stdout[-2000:] + result.stderr[-2000:])
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures')), ('48', '0'))
            escape = json.loads((out / 'generator-bug1-mutation5-escapes/result.json').read_text())
            caught = json.loads((out / 'wide-detect-mutation5/result.json').read_text())
            self.assertEqual((escape['formal_status'], caught['formal_status'], caught['failed']), ('PASS', 'FAIL', ['ap_ctrl_reserved']))
            self.assertNotIn('ap_ctrl_reserved', escape['inventory']['assert'])
            self.assertIn('`include "properties.svh"', (out / 'spec-prove/dut.sv').read_text())

    def test_a_mutant_in_the_normal_proofs_fails_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = self.run_example(out, '--demo-bug', '2')
            self.assertEqual(result.returncode, 1)
            summary = json.loads((out / 'summary.json').read_text())
            failed = {r['id'] for r in summary['results'] if r['status'] == 'fail'}
            self.assertEqual(failed, {'spec-prove', 'wide-prove', 'requirements'})

    def test_missing_systemrdl_stops_before_any_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            result = self.run_example(out, '--rdl-python', str(Path(tmp) / 'no-python'))
            self.assertEqual(result.returncode, 1)
            summary = json.loads((out / 'summary.json').read_text())
            self.assertFalse(summary['complete'])
            self.assertFalse((out / 'spec-prove').exists())


if __name__ == '__main__':
    unittest.main()
