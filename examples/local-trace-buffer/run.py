#!/usr/bin/env python3
"""On-chip trace buffer, and a field failure brought back as a fixed regression: the dump of the
trace window becomes the input of a simulation that reproduces the old revision's error."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = load('trace_model', HERE / 'model.py')
REPLAY = load('trace_replay', HERE / 'replay.py')

NAME = 'local-trace-buffer'
TOP = 'trace_tb'
SOURCES = [HERE / 'rtl/frame_monitor.sv', HERE / 'rtl/trace_buffer.sv', HERE / 'tb/trace_tb.sv']
FIELD_TRACE = HERE / 'field/issue-0001.trace'
EXTRA_INPUTS = [HERE / 'model.py', HERE / 'replay.py', FIELD_TRACE]
CONFIGS = {'d16': dict(DEPTH=16), 'd8': dict(DEPTH=8)}
ITERATIONS = {'smoke': 6, 'nightly': 20}
MUTANTS = 7
# Mutation 1 is the old revision of the frame monitor; 2..7 are errors of the trace buffer.
LABELS = {2: 'TR_STATUS', 3: 'TR_READ', 4: 'TR_COUNT', 5: 'TR_STATUS', 6: 'TR_STATUS', 7: 'TR_MARK'}
MATCH = 0x1aa                                  # a valid byte 0xaa
ALL = 0x1ff


def plain(rng, count, avoid=()):
    """Valid bytes that neither trigger a match nor look like a flag."""
    pool = [d for d in range(256) if d not in (M.FLAG, *avoid)]
    return [(1, rng.choice(pool)) for _ in range(count)]


def capture_rows(depth):
    """Every capture, trigger and readout goal on purpose."""
    rng = random.Random(depth)
    b = M.Bench(depth)
    b.reset(2)
    b.read(2)                                  # nothing captured yet: ignored
    # A full ring, then a match; one more 0xaa in the post samples must not trigger again.
    b.arm(3, value=MATCH, mask=ALL)
    b.stream(plain(rng, depth + 9, avoid=(0xaa,)) + [(1, 0xaa), (1, 0x11), (1, 0xaa), (1, 0x22), (1, 0x33)])
    b.read(depth + 2)                          # past the end as well
    # Early trigger with a mask on the high nibble, no post samples.
    b.arm(0, value=0x130, mask=0x1f0)
    b.stream([(1, 0x05), (0, 0x37), (1, 0x2c), (1, 0x3a), (1, 0x01)])
    b.read(6)
    # The longest post: the trigger sample is the oldest of the window.
    b.arm(depth - 1, value=MATCH, mask=ALL)
    b.stream(plain(rng, 2, avoid=(0xaa,)) + [(1, 0xaa)] + plain(rng, depth + 2, avoid=(0xaa,)))
    b.read(depth + 1)
    # Restart a capture, then reset in the middle of one.
    b.arm(2, value=MATCH, mask=ALL)
    b.stream(plain(rng, 4, avoid=(0xaa,)))
    b.arm(2, value=MATCH, mask=ALL)
    b.stream(plain(rng, 3, avoid=(0xaa,)))
    b.reset()
    b.idle(1)
    # The monitor's own error as the trigger: two flags and three bytes, a frame of exactly four
    # bytes, then one that is too long.
    b.arm(3, sel=1)
    b.stream([(1, M.FLAG), (1, M.FLAG), (1, 0x01), (1, 0x02), (1, 0x03),
              (1, M.FLAG), (1, 0x04), (0, 0x55), (1, 0x05), (1, 0x06), (1, 0x07),
              (1, M.FLAG), (1, 0x08), (1, 0x09), (1, 0x0a), (1, 0x0b), (1, 0x0c), (1, M.FLAG), (1, 0x0d), (1, 0x0e)])
    b.read(depth + 1)
    b.arm(1, value=MATCH, mask=ALL)            # arm again after done
    b.stream(plain(rng, 2, avoid=(0xaa,)) + [(1, 0xaa), (1, 0x44)])
    b.read(4)
    return b.rows


def field_rows(depth, old):
    """The traffic of the field failure, the monitor's error as the trigger, then the readout."""
    b = M.Bench(depth, old=old)
    b.reset(2)
    b.arm(3, sel=1)
    b.stream(M.field_stream())
    b.read(depth + 2)
    return b.rows


def replay_rows():
    """The stored dump turned into inputs; the expected error column is the specification's."""
    samples = REPLAY.parse(FIELD_TRACE.read_text())[1]
    inputs, _ = REPLAY.replay(samples)
    b = M.Bench(16)
    b.reset(2)
    b.stream(inputs)
    b.idle(2)
    return b.rows


def random_rows(seed, iterations, depth):
    rng = random.Random(seed)
    b = M.Bench(depth)
    b.reset(2)
    for _ in range(iterations):
        kind = rng.randrange(5)
        if kind == 0:
            b.arm(rng.randrange(depth), value=MATCH, mask=rng.choice((ALL, 0x1f0, 0x10f)))
            b.stream([(rng.randrange(2), rng.randrange(256)) for _ in range(rng.randrange(1, 3 * depth))])
            b.read(rng.randrange(depth + 3))
        elif kind == 1:
            b.arm(rng.randrange(depth), sel=1)
            b.stream(M.frames(rng, rng.randrange(1, 6)) + [(1, M.FLAG)] + plain(rng, M.MAXLEN + 1) + [(1, M.FLAG)])
            b.idle(rng.randrange(depth))
            b.read(rng.randrange(depth + 3))
        elif kind == 2:
            b.reset(rng.randrange(1, 3))
        elif kind == 3:
            b.stream(M.frames(rng, rng.randrange(1, 4)))
        else:
            b.cycle(arm=1, post=rng.randrange(depth), sel=rng.randrange(2), value=MATCH, mask=ALL,
                    valid=1, data=rng.randrange(256))
    b.read(depth + 1)
    return b.rows


def counts(rows):
    captures = reads = errors = 0
    previous_done = 0
    for row in rows:
        if not row[0]:
            continue
        captures += int(row[12] and not previous_done)
        previous_done = row[12]
        reads += row[14]
        errors += row[10]
    return dict(captures=captures, reads=reads, errors=errors)


def make_cases(args, parameters):
    depth = parameters['DEPTH']
    capture = capture_rows(depth)
    cases = [dict(id='capture', vectors=capture, mutation=args.demo_bug, category='functional', expected_failure=None),
             dict(id='field-fixed-revision', vectors=field_rows(depth, False), mutation=args.demo_bug,
                  category='functional', expected_failure=None),
             dict(id='replay-field-issue-0001', vectors=replay_rows(), mutation=args.demo_bug,
                  category='functional', expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_rows(seed, args.iterations, depth),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    # The old revision on the board: the trace buffer captures its error; the readout of the
    # deeper configuration is the stored dump.
    cases.append(dict(id='field-old-revision', vectors=field_rows(depth, True), mutation=1,
                      category='diagnostic', expected_failure=None))
    # The fixed regression made from the dump catches the old revision.
    cases.append(dict(id='detect-mutation1-by-replay', vectors=replay_rows(), mutation=1,
                      category='mutation', expected_failure='TR_DUT'))
    for mutation in range(2, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=capture, mutation=mutation,
                          category='mutation', expected_failure=LABELS[mutation]))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    sys.exit(runner.main(sys.modules[__name__]))
