// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#include "dot_model.hpp"
#include <stdexcept>

std::int64_t DotModel::accept(const DotTxn& t) const {
    std::int64_t sum = 0;
    for (unsigned i = 0; i < t.a.size(); i++) {
        if (t.a[i] < -128 || t.a[i] > 127 || t.b[i] < -128 || t.b[i] > 127)
            throw std::invalid_argument("operand outside signed 8 bits");
        sum += std::int64_t(t.a[i]) * t.b[i];
    }
    // Four products of signed 8-bit values lie in [-65024, 65536]; the RTL output has 18 bits.
    if (sum < -(std::int64_t(1) << 17) || sum >= (std::int64_t(1) << 17))
        throw std::logic_error("result outside signed 18 bits");
    return sum;
}
