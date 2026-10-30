#!/usr/bin/env python3
"""3x3 convolution windows from a raster stream: zero padding, stride, frame flush and back-to-back frames."""
import importlib.util
import itertools
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
NAME = 'local-conv-window'
TOP = 'conv_window_tb'
CONFIGS = {'w5h4-s1': {'W': 5, 'H': 4, 'STRIDE': 1}, 'w7h5-s2': {'W': 7, 'H': 5, 'STRIDE': 2}}
ITERATIONS = {'smoke': 6, 'nightly': 40}  # random frames per seed
SOURCES = [HERE / 'rtl/conv_window.sv', HERE / 'tb/conv_window_tb.sv']


def pack(values):
    return sum(value << (8 * i) for i, value in enumerate(values))


class Model:
    """Windows are cut from the stored frame with explicit padding; no line buffer is modelled.

    Only the timing contract is shared with the RTL: the window centred on pixel k
    leaves on the step that brings pixel k+W+1, and W+1 flush steps follow a frame.
    """

    def __init__(self, w, h, stride):
        self.w, self.h, self.stride = w, h, stride
        self.last = ((h - 1) // stride * stride, (w - 1) // stride * stride)
        self.reset()

    def reset(self):
        self.p = 0
        self.frame = []
        self.out = None

    def window(self, r, c):
        return [self.frame[(r + dr) * self.w + c + dc]
                if 0 <= r + dr < self.h and 0 <= c + dc < self.w else 0
                for dr in (-1, 0, 1) for dc in (-1, 0, 1)]

    def step(self, rst, pixel, ready):
        if not rst:
            self.reset()
            return [0, 0, 0, 0]
        enable = self.out is None or bool(ready)
        flushing = self.p >= self.w * self.h
        outputs = [int(enable and not flushing), int(self.out is not None), *(self.out or (0, 0))]
        if self.out is not None and ready:
            self.out = None
        if enable and (flushing or pixel is not None):
            if not flushing:
                self.frame.append(pixel)
            k = self.p - (self.w + 1)
            if k >= 0:
                r, c = divmod(k, self.w)
                if r % self.stride == 0 and c % self.stride == 0:
                    self.out = (pack(self.window(r, c)), int((r, c) == self.last))
            self.p += 1
            if self.p == self.w * self.h + self.w + 1:
                self.p = 0
                self.frame = []
        return outputs


class Plan:
    def __init__(self, w, h, stride):
        self.model = Model(w, h, stride)
        self.rows = []

    def cycle(self, rst=1, pixel=None, ready=1):
        outputs = self.model.step(rst, pixel, ready)
        row = [rst, int(pixel is not None), 0xa5 if pixel is None else pixel, ready, *outputs]
        self.rows.append(row)
        return row

    def stream(self, pixels, pattern=(1,), gaps=()):
        """Offer each pixel until accepted; out_ready repeats pattern; gaps insert idle cycles."""
        ready = itertools.cycle(pattern)
        for index, pixel in enumerate(pixels):
            if index in gaps:
                self.cycle(ready=next(ready))
            while not self.cycle(pixel=pixel, ready=next(ready))[4]:
                pass

    def finish(self, pattern=(1,)):
        ready = itertools.cycle(pattern)
        while self.model.p or self.model.out is not None:
            self.cycle(ready=next(ready))


def picture(w, h, seed):
    # Distinct nonzero pixels with both extremes, so leaked or misplaced pixels are visible.
    values = [(seed * 37 + 23 * i) % 254 + 1 for i in range(w * h)]
    values[0], values[-1] = 255, 1
    return values


def boundary_vectors(w, h, stride):
    p = Plan(w, h, stride)
    p.cycle(rst=0)
    p.stream(picture(w, h, 1))                                        # first frame after reset
    p.stream(picture(w, h, 2), pattern=(1, 0, 0), gaps={3, w + 2})    # waits for the flush, stalls, gaps
    p.finish(pattern=(0, 0, 1))                                       # stalls during the flush
    p.stream(picture(w, h, 3))
    p.stream(picture(w, h, 4)[:w * h // 2])
    p.cycle(rst=0)                                                    # reset in the middle of a frame
    p.stream(picture(w, h, 5))
    p.finish()
    return p.rows


def random_vectors(seed, iterations, w, h, stride):
    rng = random.Random(seed)
    p = Plan(w, h, stride)
    p.cycle(rst=0)
    for _ in range(iterations):
        pixels = [rng.randrange(256) for _ in range(w * h)]
        index = 0
        while index < len(pixels):
            if rng.randrange(400) == 0:
                p.cycle(rst=0)
                break
            offered = pixels[index] if rng.randrange(5) else None
            if p.cycle(pixel=offered, ready=int(rng.randrange(3) != 0))[4] and offered is not None:
                index += 1
    while p.model.p or p.model.out is not None:
        p.cycle(ready=int(rng.randrange(3) != 0))
    return p.rows


def counts(rows):
    return dict(accepted=sum(bool(r[0] and r[1] and r[4]) for r in rows),
                windows=sum(bool(r[0] and r[5] and r[3]) for r in rows),
                frames=sum(bool(r[0] and r[5] and r[3] and r[7]) for r in rows))


def make_cases(args, parameters):
    shape = parameters['W'], parameters['H'], parameters['STRIDE']
    base = boundary_vectors(*shape)
    cases = [dict(id='boundaries', vectors=base, mutation=args.demo_bug, category='functional',
                  expected_failure=None)]
    for seed in range(args.seed, args.seed + (3 if args.profile == 'nightly' else 1)):
        cases.append(dict(id=f'random-seed{seed}', vectors=random_vectors(seed, args.iterations, *shape),
                          mutation=args.demo_bug, category='functional', expected_failure=None))
    # Flush steps taken during a stall overwrite the held window at stride 1; at stride 2
    # most flush steps emit nothing, so the early end of the flush is seen first.
    flush_label = 'CONV_HOLD' if parameters['STRIDE'] == 1 else 'CONV_CONTROL'
    for mutation, label in ((1, 'CONV_DATA'), (2, 'CONV_DATA'), (3, 'CONV_CONTROL'), (4, flush_label)):
        cases.append(dict(id=f'detect-mutation{mutation}', vectors=base, mutation=mutation,
                          category='mutation', expected_failure=label))
    for case in cases:
        case['counts'] = counts(case['vectors'])
    return cases


if __name__ == '__main__':
    spec = importlib.util.spec_from_file_location('local_runner', HERE.parent / 'local-common/runner.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.exit(module.main(sys.modules[__name__]))
