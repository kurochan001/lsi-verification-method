#!/usr/bin/env python3
"""Rational-ratio image resize (nearest neighbour, centre aligned) against an exact rational model."""
import importlib.util
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-image-scaler'
TOP = 'image_scaler_tb'
CONFIGS = {'max12': dict(MAX_W=12, MAX_H=12), 'max24h6': dict(MAX_W=24, MAX_H=6)}
ITERATIONS = {'smoke': 4, 'nightly': 12}          # random frames per seed
SOURCES = [HERE / 'rtl/image_scaler.sv', HERE / 'tb/image_scaler_tb.sv']
EXTRA_INPUTS = [HERE / 'model.py']
MUTANTS = 9
LABELS = {1: 'SCALE_DATA', 2: 'SCALE_DATA', 3: 'SCALE_DATA', 4: 'SCALE_DATA', 5: 'SCALE_DATA',
          6: 'SCALE_LAST', 7: 'SCALE_HOLD', 8: 'SCALE_DATA', 9: 'SCALE_CONFIG'}
CONFIG, PIXEL, EXPECT = 0, 1, 2
ERROR, MIDFRAME = 1, 2                                 # flags of a configuration row
# Bit i of the tag column names a goal; the bench prints it for a row that passed.
TAGS = ['map/tie-column', 'map/tie-row', 'map/repeat-column', 'map/skip-column', 'map/repeat-row',
        'map/skip-row', 'edge/right', 'edge/bottom', 'phase/period-return', 'frame/last', 'size/max',
        'size/one', 'ratio/down', 'ratio/up', 'ratio/identity', 'config/size-change', 'config/midframe-ignored',
        'config/error-in-w-zero', 'config/error-in-w-over', 'config/error-in-h-zero', 'config/error-in-h-over',
        'config/error-out-w-zero', 'config/error-out-w-over', 'config/error-out-h-zero', 'config/error-out-h-over']
BIT = {name: 1 << i for i, name in enumerate(TAGS)}

spec = importlib.util.spec_from_file_location('image_scaler_model', HERE / 'model.py')
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)


class Plan:
    """Rows: kind, a, b, c, d, e, tags.
    config  (0): in_w in_h out_w out_h flags
    pixel   (1): value gap first outputs_before (first pixel of a frame: outputs of all earlier frames)
    expect  (2): value last stall (cycles with out_ready low once it is shown)"""

    def __init__(self, parameters, rng=None):
        self.max_w, self.max_h = parameters['MAX_W'], parameters['MAX_H']
        self.rows, self.previous, self.rng = [], None, rng or random.Random(0)
        self.frames = self.outputs = 0

    def frame(self, iw, ih, ow, oh, pixels=None, gaps=None, stalls=None, midframe=None):
        if not (1 <= min(iw, ow) and max(iw, ow) <= self.max_w and 1 <= min(ih, oh) and max(ih, oh) <= self.max_h):
            raise ValueError('frame outside the configured limits')
        if pixels is None:
            pixels = [[self.rng.randrange(256) for _ in range(iw)] for _ in range(ih)]
        out = M.resize(pixels, iw, ih, ow, oh)
        tag = BIT['config/size-change'] if self.previous not in (None, (iw, ih, ow, oh)) else 0
        if iw > ow and ih > oh:
            tag |= BIT['ratio/down']
        if iw < ow and ih < oh:
            tag |= BIT['ratio/up']
        if (iw, ih) == (ow, oh):
            tag |= BIT['ratio/identity']
        self.rows.append([CONFIG, iw, ih, ow, oh, 0, tag])
        flat = [v for row in pixels for v in row]
        for i, value in enumerate(flat):
            if midframe is not None and i == midframe[0]:
                self.rows.append([CONFIG, *midframe[1], MIDFRAME, BIT['config/midframe-ignored']])
            self.rows.append([PIXEL, value, gaps(i) if gaps else 0, int(i == 0), self.outputs if i == 0 else 0, 0, 0])
        col = [M.source_index(x, iw, ow) for x in range(ow)]
        row = [M.source_index(y, ih, oh) for y in range(oh)]
        for y in range(oh):
            for x in range(ow):
                tag = 0
                if M.tie(x, iw, ow):
                    tag |= BIT['map/tie-column']
                if M.tie(y, ih, oh):
                    tag |= BIT['map/tie-row']
                if x and col[x] == col[x - 1]:
                    tag |= BIT['map/repeat-column']
                if x and col[x] - col[x - 1] >= 2:
                    tag |= BIT['map/skip-column']
                if y and row[y] == row[y - 1]:
                    tag |= BIT['map/repeat-row']
                if (y and row[y] - row[y - 1] >= 2) or (not y and row[0] >= 1):
                    tag |= BIT['map/skip-row']
                if x == ow - 1 and col[x] == iw - 1:
                    tag |= BIT['edge/right']
                if y == oh - 1 and row[y] == ih - 1:
                    tag |= BIT['edge/bottom']
                if 0 < x and (x * iw) % ow == 0:
                    tag |= BIT['phase/period-return']
                last = int(x == ow - 1 and y == oh - 1)
                if last:
                    tag |= BIT['frame/last']
                    if iw == self.max_w and ow == self.max_w:
                        tag |= BIT['size/max']
                    if iw == 1 or ow == 1:
                        tag |= BIT['size/one']
                self.rows.append([EXPECT, out[y][x], last, stalls(y * ow + x) if stalls else 0, 0, 0, tag])
        self.previous = (iw, ih, ow, oh)
        self.frames, self.outputs = self.frames + 1, self.outputs + ow * oh
        return out

    def refused(self, iw, ih, ow, oh, goal):
        self.rows.append([CONFIG, iw, ih, ow, oh, ERROR, BIT[goal]])


def boundary_rows(parameters):
    p = Plan(parameters, random.Random(1))
    mw, mh = parameters['MAX_W'], parameters['MAX_H']
    h4, h3 = min(4, mh), min(3, mh)
    every3 = lambda i: 1 if i % 3 == 2 else 0
    stall5 = lambda i: 2 if i % 5 == 1 else 0
    p.frame(4, h4, 3, h3, gaps=every3, stalls=stall5)              # 3/4: exact ties on both axes when even
    p.frame(3, h3, 5, min(5, mh), stalls=stall5)                    # 5/3: repeats, never a tie (odd source)
    p.frame(5, 2, 5, 2)                                             # identity
    p.frame(1, 2, 3, 1)                                             # one source column, a skipped row
    p.frame(min(8, mw), min(6, mh), 3, 2, gaps=every3)              # strong reduction: skipped columns and rows
    p.frame(mw, min(3, mh), mw - 1, min(5, mh))                     # widest frames: the accumulators near their top
    p.frame(mw, 2, mw, 3, stalls=stall5)
    p.frame(6, h4, 4, min(6, mh), midframe=(5, (2, 2, 9 % mw + 1, 1)))   # sizes changed in the middle: ignored
    for goal, sizes in (('config/error-in-w-zero', (0, 2, 2, 2)), ('config/error-in-w-over', (mw + 1, 2, 2, 2)),
                        ('config/error-in-h-zero', (2, 0, 2, 2)), ('config/error-in-h-over', (2, mh + 1, 2, 2)),
                        ('config/error-out-w-zero', (2, 2, 0, 2)), ('config/error-out-w-over', (2, 2, mw + 1, 2)),
                        ('config/error-out-h-zero', (2, 2, 2, 0)), ('config/error-out-h-over', (2, 2, 2, mh + 1))):
        p.refused(*sizes, goal)
    p.frame(2, 2, 2, 2)                                             # a valid size after the refusals
    p.frame(mw, mh, 1, 1)                                           # the whole frame down to its centre pixel
    return p


def random_rows(parameters, seed, frames):
    rng = random.Random(seed)
    p = Plan(parameters, rng)
    mw, mh = parameters['MAX_W'], parameters['MAX_H']
    for _ in range(frames):
        sizes = [rng.randint(1, mw), rng.randint(1, mh), rng.randint(1, mw), rng.randint(1, mh)]
        gap = rng.choice((0, 0.2, 0.5))
        stall = rng.choice((0, 0.2, 0.5))
        gaps = [rng.randrange(1, 4) if rng.random() < gap else 0 for _ in range(sizes[0] * sizes[1])]
        stalls = [rng.randrange(1, 4) if rng.random() < stall else 0 for _ in range(sizes[2] * sizes[3])]
        p.frame(*sizes, gaps=gaps.__getitem__, stalls=stalls.__getitem__)
    return p


def make_cases(args, parameters):
    base = boundary_rows(parameters)
    plans = [('boundaries', base)] + [(f'random-seed{seed}', random_rows(parameters, seed, args.iterations))
                                      for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1))]
    cases = [dict(id=name, vectors=plan.rows, mutation=args.demo_bug, category='functional', expected_failure=None,
                  counts=dict(frames=plan.frames, outputs=plan.outputs)) for name, plan in plans]
    for mutation in range(1, MUTANTS + 1):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base.rows, mutation=mutation, category='mutation',
                          expected_failure=LABELS[mutation], counts=dict(frames=base.frames, outputs=base.outputs)))
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))
