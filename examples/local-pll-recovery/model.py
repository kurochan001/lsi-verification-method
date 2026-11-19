"""Build bounded PLL scenarios from external lock and clock availability."""
from random import Random


def vectors(parameters, seed, iterations):
    rng = Random(seed)
    timeout = parameters['TIMEOUT']
    lock_cycles = parameters['LOCK_CYCLES']
    settle = timeout + lock_cycles + 16
    rows = []

    def phase(reset_n, locked, running, duration, permit, missing, forbid=False, goals=()):
        rows.append([reset_n, locked, running, duration, permit, missing, int(forbid),
                     sum(1 << goal for goal in goals)])

    phase(0, 0, 1, 4, 0, 0, True)
    phase(1, 0, 1, settle, 0, 0, True, (0,))
    # Keep lock high long enough for two synchronization samples but below qualification.
    # The following low interval also checks delayed effects of the pulse.
    phase(1, 1, 1, lock_cycles - 2, 0, 0, True)
    phase(1, 0, 1, settle, 0, 0, True, (1,))
    phase(1, 1, 1, settle, 1, 0, goals=(2, 8))
    phase(1, 0, 1, 9, 0, 0, goals=(3,))
    phase(1, 1, 1, settle, 1, 0, goals=(4,))
    # LOCKED is deliberately stale when the generated clock has stopped.
    phase(1, 1, 0, timeout + 4, 0, 1, goals=(5,))
    phase(1, 1, 0, 8, 0, 1, True)
    phase(1, 1, 1, settle, 1, 0, goals=(6,))
    phase(0, 0, 0, 6, 0, 0, True, (7,))
    phase(1, 0, 0, settle, 0, 1, True)
    phase(1, 0, 1, settle, 0, 0, True)
    phase(1, 1, 1, settle, 1, 0)

    for _ in range(iterations):
        phase(1, 1, 1, rng.randrange(3, 12), 1, 0)
        if rng.randrange(2):
            phase(1, 0, 1, rng.randrange(9, 18), 0, 0)
        else:
            phase(1, 1, 0, settle + rng.randrange(12), 0, 1)
        phase(1, 1, 1, settle + rng.randrange(12), 1, 0)
    return rows
