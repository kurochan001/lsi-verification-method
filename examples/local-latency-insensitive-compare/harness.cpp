// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Drives either implementation with the same transaction list, checks the ready/valid
// rules on every clock, and compares the delivered results with the untimed C++ model
// as a stream: order and content only, not the cycle of each transfer.
#include "Vdut.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "dot_model.hpp"
#include "stream_compare.hpp"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

struct Failure : std::runtime_error {
    using std::runtime_error::runtime_error;
};
[[noreturn]] void fail(const std::string& label, const std::string& detail = "") {
    if (!detail.empty()) std::cout << "DETAIL " << label << ' ' << detail << '\n';
    throw Failure(label);
}
void cover(const char* goal) { std::cout << "COVER " << goal << '\n'; }

struct Step {
    std::string kind;
    DotTxn txn;
    long arg = 0;
};

std::uint64_t pack(const DotTxn& t) {
    std::uint64_t word = 0;
    for (unsigned i = 0; i < 4; i++) {
        word |= std::uint64_t(std::uint8_t(t.a[i])) << (8 * i);
        word |= std::uint64_t(std::uint8_t(t.b[i])) << (32 + 8 * i);
    }
    return word;
}
std::int64_t signed18(std::uint32_t raw) {
    std::int64_t v = raw & 0x3ffff;
    return (v & 0x20000) ? v - 0x40000 : v;
}

struct Bench {
    VerilatedContext context;
    Vdut dut{&context};
    VerilatedVcdC wave;
    std::ofstream csv, transfers, accepted_log;
    std::string dir;
    DotModel model;
    bool monitor;
    std::vector<std::int64_t> expected, actual;
    std::vector<DotTxn> expected_txn;
    unsigned long cycle = 0;
    unsigned accepted = 0, delivered = 0, cancelled = 0, resets = 0, epochs = 0, checkpoints = 0;
    bool prev_valid = false, prev_ready = false, prev_delivered = false, last_out_valid = false;
    std::int64_t prev_data = 0;
    std::string mode = "on";
    std::uint32_t state;

    Bench(const std::string& vcd, const std::string& path, unsigned seed, bool watch)
        : csv(path), monitor(watch), state(seed ? seed : 1) {
        const auto slash = path.find_last_of('/');
        dir = slash == std::string::npos ? "." : path.substr(0, slash);
        transfers.open(dir + "/transfers.csv");
        accepted_log.open(dir + "/accepted.csv");
        if (!csv || !transfers || !accepted_log) fail("LI_TRACE");
        context.traceEverOn(true);
        dut.trace(&wave, 99);
        wave.open(vcd.c_str());
        csv << "cycle,rst_n,in_valid,in_ready,out_valid,out_ready,out_data,pending\n";
        transfers << "cycle,value\n";
        accepted_log << "cycle,a0,a1,a2,a3,b0,b1,b2,b3\n";
    }
    ~Bench() {
        dut.final();
        wave.close();
    }
    std::uint32_t random() {
        state ^= state << 13;
        state ^= state >> 17;
        state ^= state << 5;
        return state;
    }
    bool ready_now() {
        if (mode == "on") return true;
        if (mode == "off") return false;
        if (mode == "alt") return cycle % 2 == 1;
        if (mode == "burst") return cycle % 14 >= 10;  // ten cycles of stall, then four of release
        if (mode == "rand") return cycle % 29 >= 6 && random() % 4 != 0;
        fail("LI_INPUT", "mode " + mode);
    }
    long pending() const { return long(expected.size()) - long(actual.size()); }

    bool tick(bool resetn, bool valid, const DotTxn& t, bool ready) {
        dut.clk = 0;
        dut.rst_n = resetn;
        dut.in_valid = valid;
        dut.in_data = pack(t);
        dut.out_ready = ready;
        dut.eval();
        wave.dump(context.time());
        context.timeInc(5);
        const bool in_ready = dut.in_ready, out_valid = dut.out_valid;
        const std::int64_t data = signed18(dut.out_data);
        csv << cycle << ',' << resetn << ',' << valid << ',' << in_ready << ',' << out_valid << ',' << ready << ','
            << data << ',' << pending() << '\n';
        bool accept_now = false;
        if (!resetn) {
            if (in_ready || out_valid) fail("LI_RESET", "cycle " + std::to_string(cycle));
            prev_valid = prev_delivered = false;
        } else {
            // A result on offer must stay on offer, unchanged, until it is taken.
            if (monitor && prev_valid && !prev_ready) {
                if (!out_valid) fail("LI_WITHDRAW", "cycle " + std::to_string(cycle));
                if (data != prev_data) fail("LI_HOLD", "cycle " + std::to_string(cycle));
            }
            const bool deliver = out_valid && ready, accept = valid && in_ready;
            if (valid && !in_ready) cover("flow/input-wait");
            if (!valid && in_ready) cover("flow/input-gap");
            if (out_valid && !ready) cover("flow/output-stall");
            if (ready && !out_valid) cover("flow/ready-without-valid");
            if (deliver && prev_valid && !prev_ready) cover("flow/stall-release");
            if (deliver && prev_delivered) cover("pipe/back-to-back");
            if (accept && out_valid && !ready) cover("pipe/accept-during-stall");
            if (accept && deliver) cover("seq/accept-on-delivery");
            if (pending() >= 4) cover("pipe/full");
            if (deliver) take(data);
            if (accept) {
                expected.push_back(model.accept(t));
                expected_txn.push_back(t);
                accepted++;
                accept_now = true;
                accepted_log << cycle;
                for (int v : t.a) accepted_log << ',' << v;
                for (int v : t.b) accepted_log << ',' << v;
                accepted_log << '\n';
            }
            prev_valid = out_valid;
            prev_ready = ready;
            prev_data = data;
            prev_delivered = deliver;
        }
        last_out_valid = out_valid;
        dut.clk = 1;
        dut.eval();
        wave.dump(context.time());
        context.timeInc(5);
        cycle++;
        return accept_now;
    }
    void take(std::int64_t data) {
        const std::size_t index = actual.size();
        actual.push_back(data);
        delivered++;
        transfers << cycle << ',' << data << '\n';
        // Only a delivery that matches the model in its position earns coverage.
        if (index >= expected.size() || data != expected[index]) return;
        const DotTxn& t = expected_txn[index];
        bool nonzero = false;
        for (unsigned i = 0; i < 4; i++) nonzero = nonzero || t.a[i] * t.b[i] != 0;
        if (data == 65536) cover("data/max-positive");
        if (data == -65024) cover("data/min-negative");
        if (data == 0 && nonzero) cover("data/zero");
        if (t.a[3] * t.b[3] < 0) cover("data/lane3-negative");
        if (index == 0 && epochs > 0) cover("reset/restart");
    }
    void idle(long n) {
        for (long i = 0; i < n; i++) tick(true, false, DotTxn{}, ready_now());
    }
    void offer(const DotTxn& t) {
        unsigned guard = 0;
        while (!tick(true, true, t, ready_now()))
            if (++guard > 2000) fail("LI_TIMEOUT", "offer");
    }
    void write_stream(const char* name, const std::vector<std::int64_t>& values) {
        std::ofstream out(dir + "/" + name);
        for (auto v : values) out << v << '\n';
    }
    void checkpoint(bool prefix_ok) {
        write_stream("stream-expected.txt", expected);
        write_stream("stream-actual.txt", actual);
        const std::string label = classify_stream(expected, actual, prefix_ok);
        if (!label.empty())
            fail(label, "epoch " + std::to_string(epochs) + " expected " + std::to_string(expected.size()) +
                            " actual " + std::to_string(actual.size()));
        checkpoints++;
    }
    void drain() {
        unsigned quiet = 0, guard = 0;
        while (quiet < 16) {
            tick(true, false, DotTxn{}, true);
            quiet = last_out_valid ? 0 : quiet + 1;
            if (++guard > 4000) fail("LI_TIMEOUT", "drain");
        }
        checkpoint(false);
        if (!actual.empty()) cover("stream/checkpoint");
    }
    void reset_epoch(const char* goal) {
        if (pending() > 0) cover(goal);
        resets++;
        tick(false, false, DotTxn{}, false);
        tick(false, false, DotTxn{}, false);
        checkpoint(true);
        cancelled += unsigned(pending());
        expected.clear();
        expected_txn.clear();
        actual.clear();
        epochs++;
    }
};

std::vector<Step> parse(const std::string& path) {
    std::ifstream in(path);
    if (!in) fail("LI_INPUT", "vectors");
    std::vector<Step> steps;
    std::string line;
    while (std::getline(in, line)) {
        std::istringstream words(line);
        Step s;
        if (!(words >> s.kind)) continue;
        if (s.kind == "T") {
            for (auto& v : s.txn.a) words >> v;
            for (auto& v : s.txn.b) words >> v;
        } else if (s.kind == "MODE") {
            std::string m;
            words >> m;
            s.kind = "MODE:" + m;
        } else if (s.kind == "IDLE" || s.kind == "RESETAFTER" || s.kind == "FILL") {
            words >> s.arg;
        } else if (s.kind != "DRAIN") {
            fail("LI_INPUT", "directive " + s.kind);
        }
        std::string rest;
        if (words.fail() || (words >> rest)) fail("LI_INPUT", line);
        steps.push_back(s);
    }
    return steps;
}

int main(int argc, char** argv) {
    try {
        if (argc != 8) fail("LI_INPUT", "arguments");
        const unsigned seed = unsigned(std::stoul(argv[2]));
        const unsigned expected_delivered = unsigned(std::stoul(argv[3]));
        const bool monitor = std::string(argv[4]) == "1";
        const auto steps = parse(argv[5]);
        Bench b(argv[6], argv[7], seed, monitor);
        b.tick(false, false, DotTxn{}, false);  // power-on reset, not counted as a scenario reset
        b.tick(false, false, DotTxn{}, false);
        unsigned planned = 0;
        for (std::size_t i = 0; i < steps.size(); i++) {
            const Step& s = steps[i];
            if (s.kind == "T") {
                b.offer(s.txn);
                planned++;
            } else if (s.kind.rfind("MODE:", 0) == 0) {
                b.mode = s.kind.substr(5);
                b.ready_now();
            } else if (s.kind == "IDLE") {
                b.idle(s.arg);
            } else if (s.kind == "DRAIN") {
                b.drain();
            } else if (s.kind == "RESETAFTER") {
                // Reset s.arg cycles after the next transaction is accepted, while it is in flight.
                if (i + 1 >= steps.size() || steps[i + 1].kind != "T") fail("LI_INPUT", "RESETAFTER");
                b.offer(steps[++i].txn);
                for (long n = 0; n < s.arg; n++) b.tick(true, false, DotTxn{}, true);
                b.reset_epoch("reset/cancel-busy");
            } else if (s.kind == "FILL") {
                // With the output blocked, offer the next transactions until one waits
                // eight cycles (the design is full), then reset with everything in flight.
                const std::string saved = b.mode;
                b.mode = "off";
                bool full = false;
                for (long n = 0; n < s.arg; n++) {
                    if (i + 1 >= steps.size() || steps[i + 1].kind != "T") fail("LI_INPUT", "FILL");
                    const DotTxn t = steps[++i].txn;
                    if (full) continue;
                    bool taken = false;
                    for (int c = 0; c < 8 && !taken; c++) taken = b.tick(true, true, t, false);
                    full = !taken;
                }
                if (!full) fail("LI_INPUT", "FILL did not fill the design");
                b.reset_epoch("reset/cancel-full");
                b.mode = saved;
            }
        }
        b.drain();
        if (b.accepted != b.delivered + b.cancelled)
            fail("LI_COMPLETION", "accepted " + std::to_string(b.accepted) + " delivered " +
                                      std::to_string(b.delivered) + " cancelled " + std::to_string(b.cancelled));
        if (b.delivered != planned || planned != expected_delivered)
            fail("LI_COMPLETION", "planned " + std::to_string(planned) + " delivered " + std::to_string(b.delivered));
        std::cout << "STAT accepted=" << b.accepted << " cancelled=" << b.cancelled
                  << " checkpoints=" << b.checkpoints << " cycles=" << b.cycle << '\n';
        std::cout << "COUNT delivered=" << b.delivered << "\nCOUNT resets=" << b.resets
                  << "\nCOUNT epochs=" << b.epochs + 1 << '\n';
        std::cout << "RESULT PASS checks=" << b.delivered << '\n';
        return 0;
    } catch (const Failure& e) {
        std::cerr << "CHECK_FAIL " << e.what() << '\n';
        return 1;
    } catch (const std::exception& e) {
        std::cerr << "ERROR " << e.what() << '\n';
        return 2;
    }
}
