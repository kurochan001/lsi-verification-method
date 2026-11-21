// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#pragma once
#include <array>
#include <cstdint>

struct DotTxn {
    std::array<int, 4> a{};
    std::array<int, 4> b{};
};

// The untimed original: one result per accepted transaction, in the order of acceptance.
// It has no clock, latency, pipeline stage or ready/valid state.
class DotModel {
public:
    std::int64_t accept(const DotTxn& t) const;
};
