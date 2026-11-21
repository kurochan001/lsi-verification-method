from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'local-common'))
from local_test_support import assert_evidence, load_example, read_json, run_example

P = load_example('local-trace-buffer')
M, R = P.M, P.REPLAY
HERE = Path(P.__file__).parent
GOALS = 18


def ring_window(samples, depth, trigger, post):
    """A third way to the window: a ring with a write pointer, as the hardware stores it."""
    ring, pointer, written = [None] * depth, 0, 0
    for index, sample in enumerate(samples[:trigger + post + 1]):
        ring[pointer] = sample
        pointer = (pointer + 1) % depth
        written += 1
    kept = min(written, depth)
    return [ring[(pointer - kept + i) % depth] for i in range(kept)]


def dump(readout, depth):
    return '\n'.join([f'# depth={depth}'] + [f'{i:02x} {s >> 8:x} {s & 0xff:02x} {t:x}' for i, (s, t) in enumerate(readout)]) + '\n'


class ModelTests(unittest.TestCase):
    def test_the_window_against_a_ring_buffer(self):
        rng = random.Random(1)
        for depth in (8, 16):
            for _ in range(200):
                n = rng.randrange(1, 3 * depth)
                trigger = rng.randrange(n)
                post = rng.randrange(depth)
                samples = [rng.randrange(1, 0x100) for _ in range(trigger + post + 1)]
                samples[trigger] = 0x1aa
                for i, s in enumerate(samples):
                    if i != trigger and s == 0xaa:
                        samples[i] = 0xab
                samples = [s if i == trigger else (s & 0xff) | 0x100 for i, s in enumerate(samples)]
                b = M.Bench(depth)
                b.reset(1)
                b.arm(post, value=0x1aa, mask=0x1ff)
                b.stream([(s >> 8, s & 0xff) for s in samples])
                b.read(depth + 1)
                window = [s for s, _ in b.readout()]
                self.assertEqual(window, ring_window(samples, depth, trigger, post))
                marks = [t for _, t in b.readout()]
                self.assertEqual(sum(marks), 1)
                self.assertEqual(window[marks.index(1)], 0x1aa)

    def test_the_monitor_accepts_double_flags_and_four_byte_frames(self):
        for old, want in ((False, []), (True, [6])):
            m = M.FrameMonitor(old)
            m.edge(0, 0, 0)
            errors = []
            for valid, data in [(1, 0x41), (1, M.FLAG), (1, M.FLAG), (1, 1), (1, 2), (1, 3), (1, 4), (1, M.FLAG)]:
                m.edge(1, valid, data)
                errors.append(m.error)
            self.assertEqual([i for i, e in enumerate(errors) if e], want, old)

    def test_legal_traffic_never_errors_in_either_revision_except_the_field_burst(self):
        rng = random.Random(7)
        for old in (False, True):
            m = M.FrameMonitor(old)
            m.edge(0, 0, 0)
            for valid, data in M.frames(rng, 500):
                m.edge(1, valid, data)
                self.assertEqual(m.error, 0)

    def test_the_stored_dump_is_the_readout_of_the_old_revision(self):
        b = M.Bench(16, old=True)
        b.reset(2)
        b.arm(3, sel=1)
        b.stream(M.field_stream())
        b.read(18)
        stored = R.parse(P.FIELD_TRACE.read_text())[1]
        self.assertEqual([((v << 8) | d, t) for v, d, t in stored], b.readout())

    def test_the_replay_reproduces_the_old_error_and_the_fixed_revision_passes(self):
        inputs, trigger = R.replay(R.parse(P.FIELD_TRACE.read_text())[1])
        for old, want in ((True, [trigger]), (False, [])):
            m = M.FrameMonitor(old)
            m.edge(0, 0, 0)
            shown = []
            for valid, data in inputs:
                shown.append(m.error)
                m.edge(1, valid, data)
            self.assertEqual([i for i, e in enumerate(shown) if e], want)

    def test_a_window_without_a_known_state_is_refused(self):
        b = M.Bench(8, old=True)
        b.reset(2)
        b.arm(3, sel=1)
        b.stream(M.field_stream())
        b.read(10)
        with self.assertRaisesRegex(R.TraceError, 'too short'):
            R.replay(R.parse(dump(b.readout(), 8))[1])

    def test_malformed_dumps_are_refused(self):
        good = P.FIELD_TRACE.read_text()
        lines = good.splitlines()
        body = [l for l in lines if not l.startswith('#')]
        bad = {
            'no depth': '\n'.join(body),
            'index out of order': good.replace(body[1], '05' + body[1][2:]),
            'two triggers': good.replace(body[0], body[0][:-1] + '1'),
            'no trigger': '\n'.join(l if l.startswith('#') else l[:-1] + '0' for l in lines),
            'too many': good.replace('depth=16', 'depth=8'),
            'short line': good + '10 1 7e\n',
        }
        for name, text in bad.items():
            with self.assertRaises(R.TraceError, msg=name):
                R.parse(text)

    def test_the_command_line_prints_rows_or_refuses(self):
        run = subprocess.run([sys.executable, str(HERE / 'replay.py'), str(P.FIELD_TRACE)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(len(run.stdout.splitlines()), len(R.replay(R.parse(P.FIELD_TRACE.read_text())[1])[0]))
        with tempfile.TemporaryDirectory() as tmp:
            short = Path(tmp) / 'short.trace'
            short.write_text('# depth=16\n00 1 41 0\n01 1 42 1\n')
            run = subprocess.run([sys.executable, str(HERE / 'replay.py'), str(short)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 1)
            self.assertIn('refused', run.stderr)

    def test_counts_follow_the_rows(self):
        rows = P.capture_rows(16)
        c = P.counts(rows)
        self.assertEqual(c['captures'], 5)
        # Runs of bytes without flags are long frames to the monitor: it reports them all.
        self.assertEqual(c['errors'], sum(row[10] for row in rows if row[0]))
        self.assertEqual(P.counts(P.field_rows(16, False))['errors'], 0)
        self.assertEqual(P.counts(P.field_rows(16, True))['errors'], 1)


class RealRunTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(shutil.which('iverilog') and shutil.which('vvp'), 'Icarus is required')

    def test_smoke_evidence_and_a_planted_bug_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'out'
            run = run_example('local-trace-buffer', out)
            self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
            assert_evidence(self, out, list(P.CONFIGS), GOALS, 24, diagnostics=2, mutants=7)
            for depth in (16, 8):
                result = read_json(out / f'd{depth}-detect-mutation1-by-replay' / 'result.json')
                self.assertEqual(result['status'], 'detected')
            broken = run_example('local-trace-buffer', Path(tmp) / 'broken', '--configuration', 'd16', '--demo-bug', '3')
            self.assertEqual(broken.returncode, 1)

    def test_seed_reproduces_the_random_rows(self):
        self.assertEqual(P.random_rows(5, 6, 16), P.random_rows(5, 6, 16))
        self.assertNotEqual(P.random_rows(5, 6, 16), P.random_rows(6, 6, 16))


if __name__ == '__main__':
    unittest.main()
