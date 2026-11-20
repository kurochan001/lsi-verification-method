"""Fault patterns and the repair verdict, found by trying every choice of rows and columns."""
from itertools import combinations
import random

PASS, REPAIRED, UNREPAIRABLE, FAILED = 0, 1, 2, 3
KIND_MUST, KIND_MUST_OVERFLOW = 1, 2


def shape(p):
    return p['ROWS'] + p['SR'], p['COLS'] + p['SC']


def good_spares(p, faults):
    """Indices of the spare rows and columns without a fault anywhere on their physical line."""
    rows = [i for i in range(p['SR']) if not any(r == p['ROWS'] + i for r, _ in faults)]
    cols = [j for j in range(p['SC']) if not any(c == p['COLS'] + j for _, c in faults)]
    return rows, cols


def main_faults(p, faults):
    return {(r, c) for r, c in faults if r < p['ROWS'] and c < p['COLS']}


def covers(p, faults):
    """Every (rows, columns) choice within the fault-free spares that covers all main faults."""
    main = main_faults(p, faults)
    good_rows, good_cols = good_spares(p, faults)
    found = []
    for row_count in range(len(good_rows) + 1):
        for rows in combinations(range(p['ROWS']), row_count):
            for col_count in range(len(good_cols) + 1):
                for cols in combinations(range(p['COLS']), col_count):
                    if all(r in rows or c in cols for r, c in main):
                        found.append((rows, cols))
    return found


def verdict(p, faults):
    """PASS without a main fault; otherwise whether any choice of spare lines covers them."""
    if not main_faults(p, faults):
        return PASS
    return REPAIRED if covers(p, faults) else UNREPAIRABLE


def must_rows(p, faults):
    """Rows of the contract's must-repair rule: more faults than fault-free spare columns."""
    main = main_faults(p, faults)
    limit = len(good_spares(p, faults)[1])
    return [r for r in range(p['ROWS']) if sum(row == r for row, _ in main) > limit]


def kind(p, faults):
    must = must_rows(p, faults)
    overflow = len(must) > len(good_spares(p, faults)[0])
    return (KIND_MUST if must and not overflow else 0) | (KIND_MUST_OVERFLOW if overflow else 0)


def masks(p, faults):
    """The stuck cells and their values, one bit per physical cell, row by row."""
    _, columns = shape(p)
    stuck = sum(1 << (r * columns + c) for r, c in faults)
    value = sum(1 << (r * columns + c) for (r, c), v in faults.items() if v)
    return stuck, value


def row(p, faults, stall=0, abort=0, late=0):
    """Vector: stuck mask, stuck values, late fault, stall, abort, verdict, retest verdict, kind."""
    rows, columns = shape(p)
    if rows * columns > 128 or any(not (0 <= r < rows and 0 <= c < columns) for r, c in faults):
        raise ValueError('fault outside the physical array, or an array of more than 128 cells')
    expect = verdict(p, faults)
    late = int(bool(late) and expect == REPAIRED)
    retest = (FAILED if late else PASS) if expect == REPAIRED else 0
    return [*masks(p, faults), late, stall, abort, expect, retest, kind(p, faults)]


def boundary_faults(p):
    """Named fault patterns; the order matters to the mutation cases of run.py."""
    R, C, SR, SC = p['ROWS'], p['COLS'], p['SR'], p['SC']
    if R < SR + SC + 1 or C < SC + 2 or R < SR + 2:
        raise ValueError('array too small for the fixed patterns')
    patterns = [
        ('clean', {}),
        # One fault off the diagonal: a spare column is enough, and row and column must not be swapped.
        ('single', {(1, 2): 1}),
        # More faults in one row than spare columns: only a spare row repairs it.
        ('must-row', {(2, c): c % 2 for c in range(SC + 1)}),
        # SR+1 rows share their SC faulty columns: columns repair what rows cannot.
        ('shared-columns', {(r, C - 1 - k): 1 for r in range(SR + 1) for k in range(SC)}),
        # A full row and a faulty column: a row and a column, crossing in the spare corner.
        ('row-and-column', {**{(0, c): 0 for c in range(SC + 1)}, **{(r, C - 1): 1 for r in range(1, SR + 1)}}),
        # A diagonal one longer than the number of spares.
        ('diagonal', {(k, k): k % 2 for k in range(SR + SC + 1)}),
        # More must-repair rows than spare rows.
        ('must-overflow', {(r, c): 1 for r in range(SR + 1) for c in range(SC + 1)}),
        # A faulty spare row leaves too few rows for SR must-repair rows.
        ('bad-spare-row', {(R, 1): 1, **{(r, c): 1 for r in range(SR) for c in range(SC + 1)}}),
        # A faulty spare row, repaired with a column instead.
        ('bad-spare-row-column', {(R, 0): 0, (3, 0): 1}),
        # A faulty spare column: with one spare column the fault becomes a must-repair row.
        ('bad-spare-column', {(0, C): 1, (2, 1): 0}),
        # Faults on spares only: nothing to repair.
        ('spares-only', {(R + SR - 1, 2): 1, (1, C + SC - 1): 0}),
    ]
    return patterns


def boundary_vectors(p):
    rows = []
    for name, faults in boundary_faults(p):
        rows.append(row(p, faults, stall=3 if name == 'must-row' else 0))
    rows.append(row(p, {(1, 2): 0}, late=1))                       # a new fault after the repair
    rows.append(row(p, {(3, 1): 1, (0, 1): 0}, stall=4, abort=1))  # reset in the middle of the test
    return rows


def random_faults(p, rng):
    rows, columns = shape(p)
    spares = p['SR'] + p['SC']
    count = rng.choice((0, 1, 2, 2, 3, spares, spares + 1, spares + 1, spares + 2, spares + 3))
    line, anchor = rng.random(), (rng.randrange(p['ROWS']), rng.randrange(p['COLS']))
    faults = {}
    for _ in range(count):
        if line < 0.2:              # several faults on one row
            cell = (anchor[0], rng.randrange(p['COLS']))
        elif line < 0.4:            # several faults on one column
            cell = (rng.randrange(p['ROWS']), anchor[1])
        elif rng.random() < 0.15:   # anywhere, spares included
            cell = (rng.randrange(rows), rng.randrange(columns))
        else:
            cell = (rng.randrange(p['ROWS']), rng.randrange(p['COLS']))
        faults[cell] = rng.randrange(2)
    return faults


def random_vectors(p, seed, iterations):
    rng = random.Random(seed)
    return [row(p, random_faults(p, rng), stall=rng.choice((0, 0, 3, 4)), abort=int(rng.random() < 0.1),
                late=int(rng.random() < 0.25)) for _ in range(iterations)]


def counts(rows):
    return dict(steps=len(rows), clean=sum(r[5] == PASS for r in rows), repaired=sum(r[5] == REPAIRED for r in rows),
                unrepairable=sum(r[5] == UNREPAIRABLE for r in rows), retests=sum(r[5] == REPAIRED for r in rows),
                late_faults=sum(r[2] for r in rows))
