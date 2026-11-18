"""List-based PRPG/parallel-signature oracle and a complete truth-table DUT spec."""

# The four output truth tables are specified independently of the RTL gates.
TRUTH = (0, 9, 1, 8, 4, 13, 7, 14, 4, 5, 5, 4, 4, 5, 7, 6)
FAULTS = tuple((site, value) for site in range(4) for value in range(2))


def logic(value, fault=None):
    result = TRUTH[value]
    if fault is not None:
        site, stuck = fault
        result = (result & ~(1 << site)) | (stuck << site)
    return result


def prpg_step(value):
    bits = [(value >> bit) & 1 for bit in range(8)]
    next_bits = [sum(bits[bit] for bit in (7, 5, 4, 3)) % 2, *bits[:7]]
    return sum(bit << index for index, bit in enumerate(next_bits))


def compact(signature, response):
    # Polynomial x^8+x^4+x^3+x^2+1, four parallel response inputs at bits 0..3.
    bits = [(signature >> bit) & 1 for bit in range(8)]
    shifted = [0, *bits[:7]]
    if bits[7]:
        for bit in (0, 2, 3, 4):
            shifted[bit] ^= 1
    for bit in range(4):
        shifted[bit] ^= (response >> bit) & 1
    return sum(bit << index for index, bit in enumerate(shifted))


def responses(seed, patterns, fault=None, alias=False):
    values = []
    for index in range(patterns):
        flip = (1 if index == 0 else 2 if index == 1 else 0) if alias else 0
        values.append(logic(seed & 15, fault) ^ flip)
        seed = prpg_step(seed)
    return values


def signature(seed, patterns, fault=None, alias=False):
    result = 0
    for response in responses(seed, patterns, fault, alias):
        result = compact(result, response)
    return result
