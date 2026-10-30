from pathlib import Path
import sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from system_test_support import SystemContract
from local_test_support import load_example, simulate_vectors

P = load_example('local-conv-window')
NO_TOP_BOTTOM_MASK = {'conv_window.sv': [('if (r < 0 || r >= H ||', 'if (')]}


def windows(rows):
    out = []
    for row in rows:
        if row[0] and row[5] and row[3]:
            out.append(([(row[6] >> (8 * i)) & 0xff for i in range(9)], row[7]))
    return out


class ExampleTests(SystemContract, unittest.TestCase):
    EXAMPLE = 'local-conv-window'
    GOALS = 17

    def test_windows_are_cut_with_zero_padding(self):
        p = P.Plan(5, 4, 1)
        p.cycle(rst=0)
        pixels = list(range(1, 21))
        p.stream(pixels)
        p.finish()
        out = windows(p.rows)
        self.assertEqual(out[0][0], [0, 0, 0, 0, 1, 2, 0, 6, 7])
        self.assertEqual(out[4][0], [0, 0, 0, 4, 5, 0, 9, 10, 0])
        self.assertEqual(out[-1][0], [14, 15, 0, 19, 20, 0, 0, 0, 0])
        self.assertEqual([last for _, last in out], [0] * 19 + [1])

    def test_stride_keeps_even_centres_and_marks_the_last(self):
        p = P.Plan(7, 5, 2)
        p.cycle(rst=0)
        p.stream(list(range(1, 36)))
        p.finish()
        out = windows(p.rows)
        self.assertEqual(len(out), 4 * 3)
        self.assertEqual([w[4] for w, _ in out], [1, 3, 5, 7, 15, 17, 19, 21, 29, 31, 33, 35])
        self.assertEqual(out[-1][1], 1)

    def test_the_next_frame_waits_for_w_plus_1_flush_steps(self):
        p = P.Plan(5, 4, 1)
        p.cycle(rst=0)
        p.stream(P.picture(5, 4, 1))
        start = len(p.rows)
        p.stream([9])
        self.assertEqual([row[4] for row in p.rows[start:]], [0] * 6 + [1])

    def test_top_and_bottom_masks_are_equivalent_mutants(self):
        # Rows above and below the frame are always zero here: the W+1 flush steps and
        # reset fill the line buffer with zeros, so removing those masks changes nothing.
        for parameters in P.CONFIGS.values():
            shape = parameters['W'], parameters['H'], parameters['STRIDE']
            for rows in (P.boundary_vectors(*shape), P.random_vectors(18, 6, *shape)):
                result = simulate_vectors(P, rows, parameters, NO_TOP_BOTTOM_MASK)
                self.assertIn('RESULT PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
