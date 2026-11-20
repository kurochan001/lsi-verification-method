"""Make clock stimuli from absolute rising-edge offsets, in picoseconds."""
from random import Random


def vectors(parameters, seed, intervals=0, fault=0):
    period = parameters['PERIOD_PS']
    minimum = parameters['MIN_PULSE_PS']
    # An unlocked short pulse followed by enough normal clocks to qualify lock.
    warmup = [[period-2000, 2000, 0, 0] for _ in range(4)]
    warmup += [[period//2, period//2, 1, 0] for _ in range(32)]

    # Exact inclusive boundaries: period +800, step 1200, TIE +1000.
    offsets = [0, 0, 0, 0, 800, 400, 0, 500, 1000, 1000, 500, 0, 0, 0]
    rng = Random(seed)
    fixed_count = len(offsets)
    offsets += [rng.randint(-200, 200) for _ in range(intervals)]
    highs = [period//2] * fixed_count
    highs += [rng.randint(minimum+600, period-minimum-600) for _ in range(intervals)]
    highs[1] = minimum
    highs[2] = period-minimum

    if fault == 1:
        highs[1] -= 1
    elif fault == 2:
        highs[2] += 1
    elif fault == 3:
        offsets[4] = parameters['PERIOD_TOL_PS'] + 1
    elif fault == 4:
        # Each period differs by only 250 ps, but error accumulates.
        offsets = [250*min(index, 5) for index in range(len(offsets))]
    elif fault == 5:
        # Two permitted periods have a forbidden difference of 1400 ps.
        offsets[4:6] = [700, 0]
    elif fault != 0:
        raise ValueError(f'unsupported clock fault {fault}')

    rises = [index*period + offset for index, offset in enumerate(offsets)]
    body = [[period//2, highs[0], 1, 1]]
    for index in range(1, len(rises)):
        gap = rises[index]-rises[index-1]
        body.append([gap-highs[index-1], highs[index], 1, 1])
    if any(low <= 1 or high <= 0 for low, high, _, _ in body):
        raise ValueError('generator produced a nonpositive or unobservable pulse')
    return warmup + body
