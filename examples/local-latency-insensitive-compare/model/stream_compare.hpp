// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

// Latency-insensitive comparison: only the order and content of the transfers count,
// never the clock cycle on which they happened.
inline bool is_subsequence(const std::vector<std::int64_t>& small, const std::vector<std::int64_t>& big) {
    std::size_t j = 0;
    for (std::size_t i = 0; i < big.size() && j < small.size(); i++)
        if (big[i] == small[j]) j++;
    return j == small.size();
}

// Returns an empty string when the actual stream equals the expected one. With prefix_ok
// (the stream was cut by a reset) a prefix is also accepted: the rest was cancelled.
// Otherwise the difference is named: LI_ORDER (same items, other order), LI_DROP (items
// missing, the rest in order), LI_DUP (extra items, each a repeat of the one before),
// LI_EXTRA (other extra items) or LI_DATA (anything else).
inline std::string classify_stream(const std::vector<std::int64_t>& expected,
                                   const std::vector<std::int64_t>& actual, bool prefix_ok) {
    if (actual == expected) return "";
    if (prefix_ok && actual.size() <= expected.size() &&
        std::equal(actual.begin(), actual.end(), expected.begin()))
        return "";
    if (actual.size() == expected.size()) {
        auto x = expected, y = actual;
        std::sort(x.begin(), x.end());
        std::sort(y.begin(), y.end());
        return x == y ? "LI_ORDER" : "LI_DATA";
    }
    if (actual.size() < expected.size()) return is_subsequence(actual, expected) ? "LI_DROP" : "LI_DATA";
    if (!is_subsequence(expected, actual)) return "LI_DATA";
    std::size_t j = 0;
    bool repeats = true;
    for (std::size_t i = 0; i < actual.size(); i++) {
        if (j < expected.size() && actual[i] == expected[j]) {
            j++;
            continue;
        }
        if (i == 0 || actual[i] != actual[i - 1]) repeats = false;
    }
    return repeats ? "LI_DUP" : "LI_EXTRA";
}
