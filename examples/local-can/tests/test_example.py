import copy
from pathlib import Path
import random
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, read_json, run_example, simulate_vectors

P = load_example('local-can')
M = P.M
ICARUS = shutil.which('iverilog') and shutil.which('vvp')
GOALS = 36


def lone(bus, item, node=0, others=False):
    """Queue one frame and return the node; the other nodes are taken off the bus unless asked."""
    for other in bus.nodes:
        other.online = others or other.index == node
    bus.nodes[node].queue.append(item)
    return bus.nodes[node]


def settle(bus):
    for _ in range(14):
        bus.step()
    return bus


class BitTests(unittest.TestCase):
    def test_crc_agrees_with_long_division(self):
        rng = random.Random(3)
        for _ in range(400):
            bits = [rng.randrange(2) for _ in range(rng.randrange(1, 100))]
            self.assertEqual(M.crc15(bits), M.crc15_division(bits))
        self.assertEqual(M.crc15([0] * 19), 0)
        self.assertEqual(M.crc15([1]), M.POLY)                 # one set bit leaves the polynomial itself

    def test_the_all_zero_frame_is_stuffed_as_worked_out_by_hand(self):
        # Identifier 0, no data: 19 zeros, CRC 0. Six groups of five zeros each take a recessive stuff bit.
        bits = M.frame_bits(0, 0, 0, 0)
        self.assertEqual(bits, [0] * 34)
        self.assertEqual(''.join(map(str, M.stuffed(bits))), '000001' * 6 + '0000')
        wire = M.wire_bits(0, 0, 0, 0)
        self.assertEqual(''.join(map(str, wire[40:])), '10' + '1' * 8)   # delimiter, ACK, delimiter, end of frame

    def test_stuffing_counts_the_stuff_bit_and_is_undone_by_the_receiver(self):
        self.assertEqual(M.stuffed([1, 1, 1, 1, 1, 0, 0, 0, 0, 1]), [1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 1, 1])
        rng = random.Random(5)
        for _ in range(200):
            item = P.frame(rng.randrange(0x7F0), rng.randrange(16), rng.getrandbits(64))
            bits = M.frame_bits(*item)
            wire = M.stuffed(bits)
            self.assertNotIn('000000', ''.join(map(str, wire)))
            self.assertNotIn('111111', ''.join(map(str, wire)))
            places, stuff = P.wire_index(bits)
            self.assertEqual([wire[k] for k in places], bits)
            self.assertEqual([wire[k] for k, _ in stuff], [value for _, value in stuff])
            self.assertEqual(len(wire), len(bits) + len(stuff))

    def test_frame_fields_and_lengths(self):
        self.assertEqual(len(M.frame_bits(0x123, 0, 8, 0)), 34 + 64)
        self.assertEqual(len(M.frame_bits(0x123, 0, 15, 0)), 34 + 64)     # a length code above 8 carries 8 bytes
        self.assertEqual(len(M.frame_bits(0x123, 1, 8, 0)), 34)           # a remote frame has no data
        bits = M.frame_bits(0x555, 0, 2, 0xA5C3 << 48)
        self.assertEqual(bits[:19], [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0])
        self.assertEqual(bits[19:35], [1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 0, 0, 0, 0, 1, 1])
        with self.assertRaises(ValueError):
            M.frame_bits(0x800, 0, 0, 0)
        with self.assertRaises(ValueError):
            M.frame_bits(1, 0, 1, 1)                                       # data beyond the length

    def test_runs_start_at_the_first_dominant_bit_and_drop_the_tail(self):
        self.assertEqual(M.runs([1, 1, 0, 0, 1, 0, 1, 1, 1]), [(0, 2), (1, 1), (0, 1)])
        self.assertEqual(M.runs([1, 1, 1]), [])


class NodeTests(unittest.TestCase):
    def run_until_quiet(self, bus, limit=6000):
        for _ in range(limit):
            bus.step()
            if bus.quiet():
                return
        self.fail('the bus did not come to rest')

    def test_one_frame_reaches_both_receivers_and_leaves_the_counters_at_zero(self):
        bus = settle(M.Bus())
        item = P.frame(0x123, 3, 0xABCDEF)
        start = bus.time
        bus.nodes[0].queue.append(item)
        self.run_until_quiet(bus)
        wire = M.wire_bits(*item)
        self.assertEqual(bus.levels[start:start + len(wire)], wire)
        self.assertEqual(bus.nodes[0].events, [('done',)])
        for node in bus.nodes[1:]:
            self.assertEqual(node.events, [('rx', *item)])
        self.assertEqual([(n.tec, n.rec) for n in bus.nodes], [(0, 0)] * 3)

    def test_the_lowest_identifier_wins_and_a_data_frame_beats_a_remote_frame(self):
        bus = settle(M.Bus())
        for node, identifier in enumerate((0x345, 0x344, 0x0FF)):
            bus.nodes[node].queue.append(P.frame(identifier, 1, node))
        self.run_until_quiet(bus)
        self.assertEqual([e[1] for e in bus.nodes[1].events if e[0] == 'rx'], [0x0FF, 0x345])
        self.assertEqual([e[1] for e in bus.nodes[2].events if e[0] == 'rx'], [0x344, 0x345])
        # 0x0FF differs from the others at the second identifier bit, 0x344 from 0x345 at the last one.
        self.assertEqual([e for e in bus.nodes[0].events if e[0] == 'lost'], [('lost', 2), ('lost', 11)])
        self.assertEqual([e for e in bus.nodes[1].events if e[0] == 'lost'], [('lost', 2)])
        bus = settle(M.Bus())
        bus.nodes[0].queue.append(P.frame(0x0F0, 2, rtr=1))
        bus.nodes[1].queue.append(P.frame(0x0F0, 2, 0x1234))
        self.run_until_quiet(bus)
        self.assertEqual([e for e in bus.nodes[0].events if e[0] == 'lost'], [('lost', 12)])
        self.assertEqual([e[2] for e in bus.nodes[2].events if e[0] == 'rx'], [0, 1])

    def test_a_lone_sender_stops_counting_at_128(self):
        bus = settle(M.Bus())
        sender = lone(bus, P.frame(0x555, 1, 0xA5))
        seen = []
        for _ in range(4000):
            bus.step()
            if not seen or seen[-1] != sender.tec:
                seen.append(sender.tec)
        self.assertEqual(seen, list(range(0, 136, 8))[:17])                 # 0, 8, ... 128, and no further
        self.assertEqual(sender.mode, 1)
        self.assertEqual([e[1] for e in sender.events if e[0] == 'err'][:3], [M.KIND['ack']] * 3)

    def test_thirty_two_transmit_errors_take_the_sender_off_the_bus_until_128_idle_sequences(self):
        bus = settle(M.Bus())
        item = P.frame(0x555, 2, 0x5AA5)
        bus.nodes[0].queue.append(item)
        place = P.wire_index(M.frame_bits(*item))[0][14]
        hit = P.Repeat(P.RX_REC, 0, place, 32)
        start, off_at = bus.time, None
        while not bus.quiet():
            bus.step()
            for kind, node, bit, length in hit(bus, start) or []:
                bus.inject(start + bit, kind, node, length)
            if off_at is None and bus.nodes[0].state == 'off':
                off_at = bus.time
            self.assertLess(bus.time - start, 6000)
        self.assertEqual(hit.used, 32)
        self.assertIsNotNone(off_at)
        recovered = next(t for t in range(off_at, bus.time) if bus.levels[t] == M.DOM and t > off_at + 30)
        self.assertGreaterEqual(recovered - off_at, 128 * 11)
        self.assertLess(recovered - off_at, 128 * 11 + 40)                  # the receivers' flags come first
        self.assertEqual(bus.nodes[0].tec, 0)
        self.assertEqual(bus.nodes[0].events[-1], ('done',))

    def test_the_flag_follows_the_state_before_the_error(self):
        node = M.Node(0)
        node.state, node.role_tx, node.tec = 'crcdel', True, 120
        node.sample(M.DOM)                                                   # form error: 120 becomes 128
        self.assertEqual((node.tec, node.flag, node.passive), (128, M.ACTIVE, True))
        node.state = 'crcdel'
        node.sample(M.DOM)
        self.assertEqual((node.tec, node.flag), (136, M.PASSIVE))

    def test_receive_counter_rules(self):
        node = M.Node(0)
        for before, after in ((0, 0), (1, 0), (127, 126), (128, 127), (200, 127)):
            node.state, node.role_tx, node.crc_ok, node.sent, node.rec = 'ack', False, True, M.DOM, before
            node.sample(M.DOM)
            self.assertEqual(node.rec, after)
        node.state, node.role_tx, node.flag, node.first, node.rec = 'wait', False, M.ACTIVE, True, 3
        node.sample(M.DOM)
        node.sample(M.DOM)
        self.assertEqual(node.rec, 11)                                       # only the first dominant bit counts
        node.state, node.role_tx, node.flag, node.first, node.rec = 'wait', False, M.OVERLOAD, True, 3
        node.sample(M.DOM)
        self.assertEqual(node.rec, 3)


class PlanTests(unittest.TestCase):
    def args(self, **changes):
        return SimpleNamespace(**{**dict(profile='smoke', seed=17, iterations=3, demo_bug=0), **changes})

    def test_seed_reproduction(self):
        parameters = P.CONFIGS['skew8']
        first = P.make_cases(self.args(), parameters)
        self.assertEqual(first, P.make_cases(self.args(), parameters))
        other = P.make_cases(self.args(seed=18), parameters)
        self.assertNotEqual(first[2]['vectors'], other[2]['vectors'])
        self.assertEqual(first[0]['vectors'], other[0]['vectors'])          # the fixed cases do not depend on the seed

    def test_plan_sizes_and_the_case_that_exposes_each_mutant(self):
        cases = P.make_cases(self.args(), P.CONFIGS['skew8'])
        self.assertEqual([c['id'] for c in cases][:3], ['protocol', 'confinement', 'random-seed17'])
        self.assertEqual(len(cases), 3 + P.MUTANTS)
        fixed = {c['id']: c['vectors'] for c in cases[:2]}
        for mutation in range(1, P.MUTANTS + 1):
            case = cases[2 + mutation]
            self.assertEqual((case['mutation'], case['expected_failure']), (mutation, P.LABELS[mutation]))
            self.assertIs(case['vectors'], fixed[P.SEEN_BY[mutation]])
        self.assertEqual(len(P.make_cases(self.args(profile='nightly'), P.CONFIGS['skew8'])), 5 + P.MUTANTS)
        self.assertEqual(len(P.make_cases(self.args(demo_bug=3), P.CONFIGS['skew8'])), 3)

    def test_every_row_is_a_known_operation_and_counts_match_the_rows(self):
        for script in (P.protocol_rows(), P.confinement_rows(), P.random_rows(5, 6)):
            self.assertTrue(all(len(row) == 6 and 0 <= row[0] <= P.WAIT for row in script.rows))
            rows = script.rows
            self.assertEqual(script.counts['runs'], sum(r[0] == P.RUN for r in rows))
            self.assertEqual(script.counts['frames'], sum(r[0] == P.RX for r in rows))
            self.assertEqual(script.counts['errors'], sum(r[0] == P.ERR for r in rows))
            self.assertEqual(script.counts['done'], sum(r[2] for r in rows if r[0] == P.DONE))
            self.assertEqual(sum(r[0] == P.START for r in rows), sum(r[0] == P.END for r in rows))

    def test_each_error_kind_and_each_rule_has_its_own_scenario(self):
        kinds = lambda script: {row[2] for row in script.rows if row[0] == P.ERR}
        self.assertEqual(kinds(P.protocol_rows()), {1, 2, 3, 4, 6})          # the ACK error needs a bus without receivers
        self.assertEqual(kinds(P.confinement_rows()) & {5}, {5})
        states = [(row[2], row[3], row[4]) for row in P.confinement_rows().rows if row[0] == P.STATE]
        self.assertIn((127, 0, 0), states)                                   # the lone sender after its first success
        self.assertTrue(any(rec >= 128 and mode == 1 for _, rec, mode in states))
        self.assertTrue(any(rec == 127 for _, rec, _ in states))

    def test_a_disturbance_far_from_any_edge_or_a_busy_start_is_refused(self):
        script = P.Script()
        item = P.frame(0x555, 0)
        with self.assertRaisesRegex(ValueError, 'too far'):
            script.clone().scenario([(0, item)], [(P.RX_DOM, 1, len(M.wire_bits(*item)) + 40, 1)])
        script.bus.nodes[1].queue.append(item)
        with self.assertRaisesRegex(ValueError, 'quiet'):
            script.scenario([(0, item)])

    def test_a_late_request_is_issued_after_the_run_it_names(self):
        script = P.Script()
        script.scenario([(0, P.frame(0x3A5, 2, 0x1234))], late=[('req', 4, 1, P.frame(0x010, 0))])
        ops = [row[0] for row in script.rows]
        second = [i for i, op in enumerate(ops) if op == P.TXREQ][1]
        self.assertEqual(ops[:second].count(P.RUN), 5)
        self.assertEqual(sum(row[2] for row in script.rows if row[0] == P.DONE), 2)


@unittest.skipUnless(ICARUS, 'Icarus required')
class RtlTests(unittest.TestCase):
    def test_real_rtl_all_configurations_and_mutants(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            result = run_example('local-can', out, '--iterations', '3', '--timeout', '60')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            summary = read_json(out / 'summary.json')
            planned = (3 + P.MUTANTS) * len(P.CONFIGS)
            self.assertEqual((summary['success'], summary['complete'], summary['planned'], summary['results']),
                             (True, True, planned, planned))
            self.assertEqual(summary['mutations_detected'], P.MUTANTS * len(P.CONFIGS))
            coverage = read_json(out / 'coverage.json')
            self.assertEqual({k: (v['hit'], v['missing']) for k, v in coverage.items()},
                             {k: (GOALS, []) for k in P.CONFIGS})
            for item in coverage.values():                       # no goal is left to the random case alone
                self.assertTrue(all(any('random' not in case for case in cases) for cases in item['hits'].values()))
            suite = ET.parse(out / 'junit.xml').getroot()
            self.assertEqual((suite.get('tests'), suite.get('failures'), suite.get('errors')),
                             (str(planned + len(P.CONFIGS)), '0', '0'))
            for record in (read_json(p) for p in out.glob('*/result.json')):
                if record['category'] != 'functional':
                    self.assertEqual(record['credited_coverage'], [])
                    self.assertEqual(record['status'], 'detected')

    def test_demo_faults_make_the_normal_regression_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            for fault in (2, 5, 7):
                out = Path(tmp) / str(fault)
                result = run_example('local-can', out, '--configuration', 'skew8', '--iterations', '1',
                                     '--demo-bug', str(fault), '--timeout', '60')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(read_json(out / f'skew8-{P.SEEN_BY[fault]}/result.json')['status'], 'fail')

    def small(self):
        script = P.Script()
        script.scenario([(0, P.frame(0x123, 1, 0x5A)), (1, P.frame(0x124, 0))])
        return script.rows

    def edited(self, op, change, which=0):
        rows = copy.deepcopy(self.small())
        index = [i for i, row in enumerate(rows) if row[0] == op][which]
        change(rows[index])
        return simulate_vectors(P, rows).stdout

    def test_each_kind_of_wrong_expectation_is_reported_by_its_own_label(self):
        self.assertIn(f'RESULT PASS checks={len(self.small())}', simulate_vectors(P, self.small()).stdout)
        cases = [
            (P.RUN, lambda row: row.__setitem__(2, row[2] + 1), 5, 'CAN_RUN'),
            (P.RUN, lambda row: row.__setitem__(1, 1 - row[1]), 0, 'CAN_RUN'),
            (P.RX, lambda row: row.__setitem__(5, row[5] ^ (1 << 56)), 0, 'CAN_RX'),
            (P.RX, lambda row: row.__setitem__(2, row[2] ^ 1), 0, 'CAN_RX'),
            (P.LOST, lambda row: row.__setitem__(2, row[2] - 1), 0, 'CAN_LOST'),
            (P.DONE, lambda row: row.__setitem__(2, row[2] + 1), 0, 'CAN_DONE'),
            (P.STATE, lambda row: row.__setitem__(3, 1), 2, 'CAN_STATE'),
            (P.STATE, lambda row: row.__setitem__(4, 1), 0, 'CAN_STATE'),
        ]
        for op, change, which, label in cases:
            with self.subTest(label=label, op=op, which=which):
                output = self.edited(op, change, which)
                self.assertIn('CHECK_FAIL ' + label, output)
                self.assertNotIn('RESULT PASS', output)

    def test_missing_and_unexpected_events_are_reported(self):
        rows = self.small()
        without_rx = [row for i, row in enumerate(rows) if i != [k for k, r in enumerate(rows) if r[0] == P.RX][-1]]
        self.assertIn('CHECK_FAIL CAN_END', simulate_vectors(P, without_rx).stdout)       # a frame nobody asked about
        last_run = [k for k, r in enumerate(rows) if r[0] == P.RUN][-1]
        self.assertIn('CHECK_FAIL CAN_END', simulate_vectors(P, rows[:last_run] + rows[last_run + 1:]).stdout)
        extra = rows[:last_run + 1] + [[P.RUN, 0, 3, 0, 0, 0]] + rows[last_run + 1:]
        self.assertIn('CHECK_FAIL CAN_TIMEOUT', simulate_vectors(P, extra).stdout)        # a run that never comes
        ghost = [row for row in rows if row[0] != P.END]
        index = [k for k, r in enumerate(ghost) if r[0] == P.STATE][0]
        ghost.insert(index, [P.ERR, 2, 1, 0, 0, 0])
        self.assertIn('CHECK_FAIL CAN_ERR', simulate_vectors(P, ghost).stdout)

    def test_the_bus_check_does_not_depend_on_a_node_reading_the_bus_right(self):
        # A node that never synchronises after the start of frame reads the wrong bits with unequal clocks.
        edit = {'can_node.sv': [('MUTATION != 8 && state != OFF', "1'b0 && state != OFF")]}
        output = simulate_vectors(P, P.protocol_rows().rows, replacements=edit).stdout
        self.assertIn('CHECK_FAIL CAN_RUN', output)
        # Sampling one quantum before the end of the bit is too late for the slowest node.
        edit = {'can_node.sv': [('localparam [5:0] SAMPLE_AT = TSEG1[5:0];', "localparam [5:0] SAMPLE_AT = TSEG1[5:0] + TSEG2[5:0] - 6'd1;")]}
        output = simulate_vectors(P, P.protocol_rows().rows, replacements=edit).stdout
        self.assertIn('CHECK_FAIL', output)
        self.assertNotIn('RESULT PASS', output)


if __name__ == '__main__':
    unittest.main()
