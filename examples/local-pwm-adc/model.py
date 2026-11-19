"""Evaluate the carrier by absolute phase and reuse the ADC deadline oracle."""
from random import Random


def vectors(parameters, adc_oracle, seed, iterations):
    half = parameters['HALF_PERIOD']
    period = 2 * half
    adc = adc_oracle(8, parameters['ACQUIRE'], parameters['CONVERT'], 1000)
    rows = []
    tick = 0
    shadow = active = (0, half // 2)
    previous_pwm = 0

    def step(reset_n=1, enable=1, config=None, voltage=None, ready=1):
        nonlocal tick, shadow, active, previous_pwm
        phase = tick % period
        level = min(phase, period-phase)
        trigger = int(reset_n and enable and phase == active[1])
        cfg_error = 0
        pwm = 0
        goals = 0
        if voltage is None:
            voltage = len(rows)*1733 % 258000 - 1000

        if not reset_n:
            shadow = active = (0, half // 2)
            tick = 0
        else:
            if config is not None:
                duty, sample = config
                if 0 <= duty <= half and 0 < sample < half:
                    shadow = config
                    if enable and phase != 0 and shadow != active:
                        goals |= 1 << 3
                else:
                    cfg_error = 1
                    goals |= 1 << 4
            if enable:
                if phase == 0:
                    if active != shadow:
                        goals |= 1 << 2
                    active = shadow
                pwm = int(active[0] == half or level < active[0])
                tick += 1
                if trigger:
                    goals |= 1 << 0
                if phase == period - active[1]:
                    goals |= 1 << 1
                if active[0] == 0:
                    goals |= 1 << 5
                if active[0] == half:
                    goals |= 1 << 6
            else:
                tick = 0
                if previous_pwm:
                    goals |= 1 << 7
                if phase == active[1]:
                    goals |= 1 << 11
        previous_pwm = pwm
        outputs, adc_goals = adc.step(reset_n, trigger, voltage, ready)
        if outputs[2]:
            goals |= 1 << 8
        if outputs[3] and not ready:
            goals |= 1 << 9
        if adc_goals & (1 << 7):
            goals |= 1 << 10
        config_duty, config_sample = config or (0, 0)
        rows.append([reset_n, enable, int(config is not None), config_duty, config_sample,
                     voltage & 0xffffffff, ready, trigger, pwm, *active, cfg_error, *outputs, goals])

    def run(count, ready=1):
        for _ in range(count):
            step(ready=ready)

    step(reset_n=0)
    run(period)                        # 0% PWM still permits sampling.
    step(config=(half, 1))             # A write at the boundary applies immediately.
    step(config=(half-1, half-1))      # This write waits for the next boundary.
    run(period-2)
    run(2*period)
    step(config=(half+1, 0))           # Invalid settings are rejected.
    run(period-1)
    step(config=(half, 2), ready=0)
    run(3*period-1, ready=0)           # Later triggers see a held ADC result.
    step(enable=0)
    step(enable=0, config=(0, 1))
    step()                              # Rearm at the trough.
    step(enable=0)                     # Suppress the event that would occur at level 1.
    step()
    step()                              # Start a conversion.
    step(reset_n=0)                    # Cancel it before acquisition/conversion completes.
    run(period)
    step(reset_n=0)
    run(2*period)

    rng = Random(seed)
    for _ in range(iterations):
        config = (rng.randrange(half+2), rng.randrange(half+1)) if rng.randrange(11) == 0 else None
        step(int(rng.randrange(61) != 0), int(rng.randrange(23) != 0), config,
             rng.randrange(-1000, 262000), rng.randrange(2))
    for _ in range(parameters['ACQUIRE'] + parameters['CONVERT'] + 2):
        step(enable=0)
    return rows
