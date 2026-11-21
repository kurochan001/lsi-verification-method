import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import model as M

P = load_example('local-formal-data-integrity')
HARNESS = (HERE / 'data_integrity_formal.sv').read_text()
MODULES = {name: body for name, body in re.findall(r'^module (\w+)(.*?)^endmodule', HARNESS, re.M | re.S)}
PLAN = P.plan(P.BOUND, 0)


def labels(text, kind):
    return set(re.findall(r'\b(\w+): ' + kind + r'\b', text))


class PlanTests(unittest.TestCase):
    def test_every_shape_is_proved_and_mutants_are_checked_without_the_invariants(self):
        self.assertEqual(len(PLAN), 26)
        self.assertEqual(len({c['id'] for c in PLAN}), 26)
        proofs = [c for c in PLAN if c['category'] == 'normal' and c['mode'] == 'prove']
        self.assertEqual([c['id'].split('-')[0] for c in proofs], list(P.SHAPES))
        for c in proofs:
            self.assertEqual((c['depth'], c['expect']), (P.PROOF_DEPTH, 'PASS'))
            self.assertEqual({k: c['parameters'][k] for k in ('MUTATION', 'AUXILIARY', 'AVAILABLE', 'SIDEBAND')},
                             dict(MUTATION=0, AUXILIARY=1, AVAILABLE=1, SIDEBAND=1))
        mutants = [c for c in PLAN if c['category'] == 'mutation']
        self.assertEqual(len(mutants), 14)
        for c in mutants:
            self.assertEqual((c['mode'], c['expect'], c['parameters']['AUXILIARY']), ('bmc', 'FAIL', 0))
            self.assertIn(c['failure'], P.CHECKS | {'ap_available'})
            self.assertNotEqual(c['parameters']['MUTATION'], 0)

    def test_each_limit_is_a_wrong_design_that_passes_and_has_a_task_that_finds_it(self):
        limits = {c['id']: c for c in PLAN if c['category'] == 'diagnostic'}
        self.assertEqual(set(limits), {'fifo12-bound10-misses-mutation2', 'axis4-data-only-misses-mutation1',
                                       'axis4-data-only-misses-mutation2', 'width-tracking-only-misses-mutation5'})
        found = {c['id'] for c in PLAN if c['category'] == 'mutation'}
        for name, c in limits.items():
            self.assertEqual(c['expect'], 'PASS')
            self.assertNotEqual(c['parameters']['MUTATION'], 0)
            shape, mutation = name.split('-')[0], name.rsplit('-', 1)[-1]
            self.assertIn(f'{shape}-detect-{mutation}', found)
        bounded = limits['fifo12-bound10-misses-mutation2']
        self.assertEqual((bounded['mode'], bounded['depth']), ('bmc', 10))
        # The fault needs every entry written first, so the short bound must be shorter than the FIFO.
        self.assertGreater(bounded['parameters']['DEPTH'], bounded['depth'])
        self.assertEqual(limits['axis4-data-only-misses-mutation1']['parameters']['SIDEBAND'], 0)
        self.assertEqual(limits['width-tracking-only-misses-mutation5']['parameters']['AVAILABLE'], 0)

    def test_demo_bug_reaches_one_proof_only(self):
        changed = [c['id'] for c, d in zip(PLAN, P.plan(P.BOUND, 3)) if c != d]
        self.assertEqual(changed, ['axis4-integrity-proof'])

    def test_requirements_name_every_task_once(self):
        goals = [g for r in json.loads((HERE / 'requirements.json').read_text())['requirements'] for g in r['goals']]
        self.assertEqual(sorted(goals), sorted(c['id'] for c in PLAN))


class HarnessTests(unittest.TestCase):
    def test_property_sets_are_the_labels_in_the_harness(self):
        for target, module in (('fifo', 'fifo_integrity'), ('axis', 'axis_integrity'), ('width', 'width_integrity')):
            text = MODULES[module]
            self.assertEqual(labels(text, 'assert'), P.CHECKS | {'ap_available'} | P.AUXILIARY[target], module)
            self.assertEqual(labels(text, 'cover'), P.COVERS[target], module)
            self.assertEqual(labels(text, 'assume'), set(), module)
        self.assertEqual(labels(MODULES['data_integrity_formal'], 'assume'), {'as_initial_reset'})

    def test_the_only_assumption_is_the_initial_reset(self):
        # The invariants needed by induction are proved, not assumed.
        self.assertEqual(len(re.findall(r'\bassume\b', re.sub(r'//.*', '', HARNESS))), 1)
        for c in PLAN:
            self.assertEqual(P.properties({}, c)['assume'], {'as_initial_reset'})
        proof = P.properties({}, PLAN[0])
        self.assertTrue(P.AUXILIARY['fifo'] <= proof['assert'])
        mutant = next(c for c in PLAN if c['category'] == 'mutation')
        self.assertFalse(P.AUXILIARY['fifo'] & P.properties({}, mutant)['assert'])

    def test_every_internal_wire_is_connected_over_its_whole_width(self):
        for c in PLAN:
            target = P.target_of(c)
            module = MODULES[f'{target}_integrity']
            declared = set(re.findall(r'\(\* keep \*\) wire (?:\[[^\]]+\] )?(x_\w+);', module))
            script = P.prepare({}, c)
            connected = re.findall(rf'^connect -set {target}\.check\.(x_\w+)(\[\d+:\d+\])? {target}\.check\.dut\.(\S+)$', script, re.M)
            self.assertEqual({name for name, _, _ in connected}, declared, c['id'])
            self.assertEqual(len(connected), script.count('connect -set'))
            slices = sorted(tuple(map(int, s[1:-1].split(':'))) for name, s, _ in connected if name == 'x_memory')
            if target in P.MEMORY_WIDTH:
                width, depth = P.MEMORY_WIDTH[target], c['parameters']['DEPTH']
                self.assertEqual(slices, [((i + 1) * width - 1, i * width) for i in range(depth)])
            else:
                self.assertEqual(slices, [])
            # The design is flattened before it is connected, and the parameters are set on the top.
            self.assertLess(script.index('flatten'), script.index('connect'))
            self.assertIn(f"-set MUTATION {c['parameters']['MUTATION']} ", script)

    def test_existing_designs_are_read_where_they_are(self):
        names = [str(p.relative_to(HERE.parent)) for p in P.SOURCES]
        self.assertEqual(names, ['local-fifo/rtl/sync_fifo.sv', 'local-axis/rtl/axis_packet_fifo.sv',
                                 'local-formal-data-integrity/rtl/width_downsizer.sv',
                                 'local-formal-data-integrity/data_integrity_formal.sv'])
        for p in P.SOURCES:
            self.assertTrue(p.is_file(), p)

    def test_mutants_exist_in_the_designs(self):
        numbers = {shape: set(table) for shape, table in P.DETECTED.items()}
        for shape, source in (('fifo3', P.SOURCES[0]), ('axis4', P.SOURCES[1]), ('width', P.SOURCES[2])):
            in_rtl = {int(n) for n in re.findall(r'MUTATION\s*[!=]=\s*(\d+)', source.read_text())}
            self.assertEqual(numbers[shape], in_rtl, shape)


class ModelTests(unittest.TestCase):
    def test_the_correct_converter_violates_nothing_in_any_reachable_state(self):
        found, states = M.search(0)
        self.assertIsNone(found)
        self.assertGreater(states, 50)

    def test_exhaustive_search_names_the_check_the_plan_expects(self):
        for mutation, label in P.DETECTED['width'].items():
            found, _ = M.search(mutation)
            self.assertIsNotNone(found, mutation)
            self.assertIn(label, found[1], mutation)

    def test_a_word_that_is_never_offered_violates_no_tracking_check(self):
        self.assertIsNone(M.search(5, M.CHECKS[:3])[0])
        self.assertEqual(M.search(5)[0][1], {'ap_available'})

    def test_swapped_halves_are_seen_by_the_content_check_alone(self):
        self.assertIsNone(M.search(1, ('ap_no_spurious', 'ap_no_overflow', 'ap_available'))[0])


class ReadmeTests(unittest.TestCase):
    def test_table_of_mutants_matches_the_plan(self):
        text = (HERE / 'README.md').read_text()
        rows = re.findall(r'^\| (FIFO|AXI4-Stream|幅変換) \| (\d) \|[^|]*\| `(\w+)` \|', text, re.M)
        shape = {'FIFO': 'fifo3', 'AXI4-Stream': 'axis4', '幅変換': 'width'}
        self.assertEqual({(shape[t], int(m)): label for t, m, label in rows},
                         {(s, m): label for s, table in P.DETECTED.items() for m, label in table.items()})
        self.assertIn(f'{len(PLAN)}タスク', text)


if __name__ == '__main__':
    unittest.main()
