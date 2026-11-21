#!/usr/bin/env python3
"""Exhaustive search of the width converter with a one-item tracker, for a word of two 1-bit halves.

Written from the description in the README, not from the SystemVerilog. With 1-bit halves every
reachable state can be enumerated, so this states independently which check each mutant violates
first and that a mutant which never offers a word violates none of the tracking checks.
"""
from collections import deque
import itertools

CHECKS = ('ap_content', 'ap_no_spurious', 'ap_no_overflow', 'ap_available')
RESET = (0, 0, 0, 0, 0, 0, 0, 0, 0)  # low, high, busy, phase | beats, tracking, ahead, half | unused


def outputs(state, mutation, s_valid, m_ready):
    low, high, busy, phase = state[:4]
    hidden = mutation == 5 and not phase and low == 0
    m_valid = bool(busy) and not hidden
    last = m_valid and m_ready and phase
    s_ready = (not busy) or ((m_valid and phase) if mutation == 2 else last)
    send_high = bool(phase) != (mutation == 1)
    m_data = (high ^ (1 if mutation == 4 and low == 1 else 0)) if send_high else low
    return m_valid, bool(s_ready), m_data, bool(last)


def step(state, mutation, tag, s_valid, s_data, m_ready, pick):
    """One clock edge: the labels violated before the edge, and the state after it."""
    low, high, busy, phase, beats, tracking, ahead, half, _ = state
    m_valid, s_ready, m_data, last = outputs(state, mutation, s_valid, m_ready)
    accept = s_valid and s_ready
    pop = m_valid and m_ready
    after_pop = beats - 1 if pop else beats
    violated = set()
    if m_valid and tracking and ahead == 0 and m_data != (tag[1] if half else tag[0]):
        violated.add('ap_content')
    if pop and beats == 0:
        violated.add('ap_no_spurious')
    if accept and after_pop != 0:
        violated.add('ap_no_overflow')
    if beats != 0 and not m_valid:
        violated.add('ap_available')
    # The converter.
    new_phase = phase
    if pop and not (mutation == 3 and not phase and s_valid and not s_ready):
        new_phase = 1 - phase
    new_low, new_high, new_busy = low, high, busy
    if accept:
        if mutation == 6 and busy and s_data == (low, high):
            new_busy = 0
        else:
            new_low, new_high, new_busy, new_phase = s_data[0], s_data[1], 1, 0
    elif last:
        new_busy = 0
    # The tracker. Counters saturate so that a faulty design cannot make the search unbounded.
    new_beats = min(3, max(0, after_pop) + (2 if accept else 0))
    start = accept and pick and not tracking and s_data == tag
    new_tracking, new_ahead, new_half = tracking, ahead, half
    if start:
        new_tracking, new_ahead, new_half = 1, max(0, after_pop), 0
    elif pop and tracking:
        if ahead != 0:
            new_ahead = ahead - 1
        elif not half:
            new_half = 1
        else:
            new_tracking = 0
    return violated, (new_low, new_high, new_busy, new_phase, new_beats, new_tracking, new_ahead, new_half, 0)


def search(mutation, checks=CHECKS):
    """Breadth first over every tag and input: (depth of the first violation, labels violated there), or None."""
    words = list(itertools.product((0, 1), repeat=2))
    inputs = [(v, d, r, p) for v in (0, 1) for d in words for r in (0, 1) for p in (0, 1)]
    best = None
    states = 0
    for tag in words:
        seen = {RESET}
        frontier = deque([(RESET, 0)])
        while frontier:
            state, depth = frontier.popleft()
            if best and depth > best[0]:
                break
            for s_valid, s_data, m_ready, pick in inputs:
                violated, following = step(state, mutation, tag, s_valid, s_data, m_ready, pick)
                violated &= set(checks)
                if violated:
                    if best is None or depth < best[0]:
                        best = (depth, set(violated))
                    elif depth == best[0]:
                        best[1].update(violated)
                elif following not in seen:
                    seen.add(following)
                    frontier.append((following, depth + 1))
        states += len(seen)
    return best, states


if __name__ == '__main__':
    for mutation in range(7):
        found, states = search(mutation)
        print(mutation, 'none' if found is None else (found[0], sorted(found[1])), states)
    print('5 without ap_available', search(5, CHECKS[:3])[0])
