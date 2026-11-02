// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#pragma once
#include <array>
#include <cstdint>
#include <stdexcept>

struct FirResult {
    int value;
    std::int64_t sum;
    bool clip_high,clip_low,history;
};

// Transaction model: no RTL clocks, ready/valid state or pipeline counters.
class FirReference {
    unsigned width_;
    bool faulty_;
    std::array<int,2> past_{};
public:
    explicit FirReference(unsigned width,bool faulty=false):width_(width),faulty_(faulty) {
        if(width!=8 && width!=12)throw std::invalid_argument("unsupported FIR width");
    }
    void reset(){past_={0,0};}
    FirResult accept(int sample);
};
