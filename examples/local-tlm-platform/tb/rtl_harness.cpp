// Runs the C driver against the peripheral RTL. Every driver access becomes a real
// APB-style transfer: one setup edge, wait edges while pready is low, one access edge.
#include "Vperiph_sys.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "app.h"
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>

namespace {
struct Rig {
    VerilatedContext context;
    // Registers start from random values instead of zero (the model is built with
    // --x-initial unique), so state that reset forgets to clear shows up.
    bool randomized;
    Vperiph_sys dut{&context};
    VerilatedVcdC trace;
    uint64_t cycle = 0, limit = 0;
    bool race_seen = false, wait_seen = false, period_seen = false, have_expiry = false;
    uint64_t last_expiry = 0;
    uint32_t load = 0;

    Rig(const char *wave, uint64_t cycle_limit, uint32_t seed)
        : randomized((context.randReset(2), context.randSeed(int(seed & 0x7fffffffu) | 1), true)), limit(cycle_limit) {
        context.traceEverOn(true);
        dut.trace(&trace, 99);
        trace.open(wave);
        dut.clk = 0; dut.rst_n = 0; dut.psel = 0; dut.penable = 0; dut.pwrite = 0; dut.paddr = 0; dut.pwdata = 0;
        dut.eval();
    }
    ~Rig() { dut.final(); trace.close(); }

    [[noreturn]] void fail(const char *label) {
        std::printf("CHECK_FAIL %s\n", label);
        std::fflush(stdout);
        trace.flush();
        std::exit(1);
    }
    // One rising edge. The bench looks at the settled signals just before it.
    void tick() {
        dut.eval();
        bool acknowledge = dut.psel && dut.penable && dut.pready && dut.pwrite && !dut.pslverr &&
                           dut.paddr == APP_STATUS && (dut.pwdata & 1u);
        if (acknowledge && dut.timer_expire && !race_seen) {
            race_seen = true;
            std::printf("COVER race/clear-set\n");
        }
        if (!(dut.psel && dut.penable) && (dut.pready || dut.pslverr)) fail("PLAT_PROTOCOL");
        // RTL-only timing: while the timer runs untouched, expiries are LOAD+1 cycles apart.
        if (dut.timer_expire) {
            if (have_expiry && cycle - last_expiry != uint64_t(load) + 1) fail("PLAT_PERIOD");
            if (have_expiry && !period_seen) {
                period_seen = true;
                std::printf("COVER timer/period\n");
            }
            have_expiry = true;
            last_expiry = cycle;
        }
        if (dut.psel && dut.penable && !dut.pready && !wait_seen) {
            wait_seen = true;
            std::printf("COVER bus/wait-state\n");
        }
        trace.dump(context.time()); context.timeInc(5);
        dut.clk = 1; dut.eval();
        trace.dump(context.time()); context.timeInc(5);
        dut.clk = 0; dut.eval();
        if (++cycle > limit) fail("PLAT_TIMEOUT");
    }
    int transfer(uint32_t address, uint32_t data, bool write, uint32_t *value) {
        dut.psel = 1; dut.penable = 0; dut.pwrite = write; dut.paddr = address & 0xffffu; dut.pwdata = data;
        tick();
        dut.penable = 1; dut.eval();
        for (unsigned waited = 0; !dut.pready; waited++) {
            if (waited > 8) fail("PLAT_BUS");
            tick();
        }
        int error = dut.pslverr ? 1 : 0;
        if (value) *value = dut.prdata;
        tick();
        dut.psel = 0; dut.penable = 0; dut.eval();
        if (write && !error && (address == APP_LOAD || address == APP_CTRL)) {
            if (address == APP_LOAD) load = data & 0xffffu;
            have_expiry = false;
        }
        return error;
    }
    void reset() {
        dut.rst_n = 0;
        for (int i = 0; i < 3; i++) tick();
        dut.rst_n = 1;
        tick();
    }
};

int read32(void *user, uint32_t address, uint32_t *value) {
    int error = static_cast<Rig *>(user)->transfer(address, 0, false, value);
    std::printf("ACCESS R %08x %08x %d\n", address, *value, error);
    return error;
}
int write32(void *user, uint32_t address, uint32_t value) {
    int error = static_cast<Rig *>(user)->transfer(address, value, true, nullptr);
    std::printf("ACCESS W %08x %08x %d\n", address, value, error);
    return error;
}
int irq(void *user) {
    Rig *rig = static_cast<Rig *>(user);
    rig->dut.eval();
    return rig->dut.irq ? 1 : 0;
}
void idle(void *user) { static_cast<Rig *>(user)->tick(); }
void note(void *, const char *name, uint32_t value) { std::printf("NOTE %s %08x\n", name, value); }
}  // namespace

int main(int argc, char **argv) {
    if (argc != 9) {
        std::fprintf(stderr, "usage: irqs load seed race lead wait_limit cycle_limit wave\n");
        return 2;
    }
    app_config config{};
    config.irqs = std::stoul(argv[1]); config.load = std::stoul(argv[2]); config.seed = std::stoul(argv[3]);
    config.race = std::stoul(argv[4]); config.lead = std::stoul(argv[5]); config.wait_limit = std::stoul(argv[6]);
    Rig rig(argv[8], std::stoull(argv[7]), config.seed);
    rig.reset();
    app_platform platform{&rig, read32, write32, irq, idle, note};
    int result = app_run(&platform, &config);
    for (uint32_t word = 0; word < 64; word++) {
        uint32_t value = 0;
        if (rig.transfer(APP_MEM + 4 * word, 0, false, &value)) rig.fail("PLAT_BUS");
        std::printf("MEM %02x %08x\n", word, value);
    }
    std::printf("RESULT app=%d cycles=%llu\nEND\n", result, static_cast<unsigned long long>(rig.cycle));
    return 0;
}
