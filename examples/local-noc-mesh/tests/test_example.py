from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import load_example, simulate_vectors
from system_test_support import SystemContract

P = load_example('local-noc-mesh')


class MeshTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-noc-mesh'
    GOALS = 13

    def test_routes_cover_self_horizontal_vertical_and_two_hops(self):
        for src in range(4):
            for dst in range(4):
                node = src
                path = []
                while node != dst and P.route_of(node, dst) is not None:
                    port = P.route_of(node, dst)
                    self.assertIn(port, (1, 2))
                    path.append(port)
                    node += port
                    self.assertLessEqual(len(path), 2)
                expected = ((src & 1) <= (dst & 1) and (src >> 1) <= (dst >> 1))
                self.assertEqual(node == dst, expected)
                self.assertEqual(path, sorted(path))
                if node == dst:
                    self.assertEqual(P.route_of(node, dst), 0)

    def test_full_backpressure_then_drain_with_tag_wrap(self):
        for parameters in P.CONFIGS.values():
            p = P.Plan(parameters['BUF'])
            p.step(rst=0)
            for packet in range(25):
                p.send(0, 3, packet)
            for _ in range(16):
                p.inject(0, 1, 5, e_ready=0)
            self.assertFalse(p.ready_bits() & 1)
            p.drain()
            self.assertTrue(p.settled())
            result = simulate_vectors(P, p.rows, parameters)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_wrong_data_on_north_link_is_detected(self):
        p = P.Plan(2)
        p.step(rst=0)
        p.send(0, 2, 9)
        p.drain()
        result = simulate_vectors(P, p.rows, {'BUF': 2},
                                  {'router.sv': [('assign w_out_pkt = outp[2];',
                                                  "assign w_out_pkt = outp[2] ^ 12'h001;")]})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('CHECK_FAIL MESH_DATA', result.stdout)
