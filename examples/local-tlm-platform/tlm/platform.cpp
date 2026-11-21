// Loosely timed TLM-2.0 virtual platform: a host thread runs the C driver, a router sends
// each blocking transaction to the memory or the timer, and the timer raises a level.
// An access costs one cycle of annotated delay and the host waits it out after each one.
// The timing is approximate on purpose: there is no setup phase and no wait state.
#include <systemc>
#include <tlm>
#include <tlm_utils/simple_initiator_socket.h>
#include <tlm_utils/simple_target_socket.h>
#include "app.h"
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>

#ifndef TLM_MUTATION
#define TLM_MUTATION 0
#endif

using namespace sc_core;
static const sc_time CYCLE(10, SC_NS);

static bool fits(tlm::tlm_generic_payload &p) {
    return p.get_data_length() == 4 && p.get_streaming_width() == 4 && !p.get_byte_enable_ptr();
}

struct Memory : sc_module {
    tlm_utils::simple_target_socket<Memory> socket;
    uint32_t words[64] = {};
    SC_CTOR(Memory) : socket("socket") { socket.register_b_transport(this, &Memory::transport); }
    void transport(tlm::tlm_generic_payload &p, sc_time &delay) {
        uint64_t a = p.get_address();
        delay += CYCLE;
        if (!fits(p) || (a & 3) || a >= 256) { p.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE); return; }
        if (p.is_write()) std::memcpy(&words[a / 4], p.get_data_ptr(), 4);
        else std::memcpy(p.get_data_ptr(), &words[a / 4], 4);
        p.set_response_status(tlm::TLM_OK_RESPONSE);
    }
};

struct Timer : sc_module {
    tlm_utils::simple_target_socket<Timer> socket;
    uint32_t load = 0, expired = 0, frozen = 0;
    bool en = false, ie = false, pending = false, overrun = false, expired_once = false;
    sc_time next_expiry, last_expiry;
    sc_event changed;
    SC_HAS_PROCESS(Timer);
    explicit Timer(sc_module_name name) : sc_module(name), socket("socket") {
        socket.register_b_transport(this, &Timer::transport);
        SC_THREAD(run);
    }
    // TLM_MUTATION 2: the enable is ignored.
    bool level() const { return pending && (ie || TLM_MUTATION == 2); }
    uint32_t count() const {
        if (!en) return frozen;
        return uint32_t((next_expiry - sc_time_stamp()) / CYCLE);
    }
    void run() {
        for (;;) {
            if (!en) { wait(changed); continue; }
            sc_time target = next_expiry;
            wait(target - sc_time_stamp(), changed);
            if (!en || target != next_expiry || sc_time_stamp() != target) continue;
            if (pending) overrun = true;
            pending = true;
            expired = (expired + 1) & 0xff;
            expired_once = true;
            last_expiry = sc_time_stamp();
            next_expiry = sc_time_stamp() + (load + 1) * CYCLE;
        }
    }
    void transport(tlm::tlm_generic_payload &p, sc_time &delay) {
        uint64_t a = p.get_address();
        delay += CYCLE;
        if (!fits(p) || (a & 3) || a > 0x10) { p.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE); return; }
        uint32_t v = 0;
        if (p.is_write()) {
            std::memcpy(&v, p.get_data_ptr(), 4);
            switch (a) {
            case 0x00: load = v & 0xffff; break;
            case 0x04: {
                bool start = (v & 1) && !en;
                if (en && !(v & 1)) frozen = count();
                en = v & 1; ie = (v >> 1) & 1;
                if (start) { expired = 0; next_expiry = sc_time_stamp() + (load + 1) * CYCLE; }
                changed.notify(SC_ZERO_TIME);
                break;
            }
            case 0x08:
                if (v & 1) {
                    // An expiry processed at this same instant keeps pending set.
                    // TLM_MUTATION 1: the acknowledge wins and the expiry is lost.
                    bool same = expired_once && last_expiry == sc_time_stamp();
                    if (!same || TLM_MUTATION == 1) pending = false;
                }
                if (v & 2) overrun = false;
                break;
            default: break;  // COUNT and EXPIRED ignore writes
            }
        } else {
            switch (a) {
            case 0x00: v = load; break;
            case 0x04: v = (ie ? 2u : 0u) | (en ? 1u : 0u); break;
            case 0x08: v = (overrun ? 2u : 0u) | (pending ? 1u : 0u); break;
            case 0x0c: v = count(); break;
            default: v = expired; break;
            }
            std::memcpy(p.get_data_ptr(), &v, 4);
        }
        p.set_response_status(tlm::TLM_OK_RESPONSE);
    }
};

struct Router : sc_module {
    tlm_utils::simple_target_socket<Router> socket;
    tlm_utils::simple_initiator_socket<Router> memory, timer;
    SC_CTOR(Router) : socket("socket"), memory("memory"), timer("timer") {
        socket.register_b_transport(this, &Router::transport);
    }
    void transport(tlm::tlm_generic_payload &p, sc_time &delay) {
        uint64_t a = p.get_address();
        if (a < 0x100) memory->b_transport(p, delay);
        else if (a >= APP_TIMER && a < APP_TIMER + 0x20) {
            p.set_address(a - APP_TIMER);
            timer->b_transport(p, delay);
            p.set_address(a);
        } else {
            delay += CYCLE;
            p.set_response_status(tlm::TLM_ADDRESS_ERROR_RESPONSE);
        }
    }
};

struct Host : sc_module {
    tlm_utils::simple_initiator_socket<Host> socket;
    Timer *timer = nullptr;
    app_config config{};
    int result = 0;
    bool done = false;
    SC_HAS_PROCESS(Host);
    explicit Host(sc_module_name name) : sc_module(name), socket("socket") { SC_THREAD(main); }
    int transfer(uint32_t address, uint32_t *data, bool write) {
        tlm::tlm_generic_payload p;
        sc_time delay = SC_ZERO_TIME;
        p.set_command(write ? tlm::TLM_WRITE_COMMAND : tlm::TLM_READ_COMMAND);
        p.set_address(address);
        p.set_data_ptr(reinterpret_cast<unsigned char *>(data));
        p.set_data_length(4);
        p.set_streaming_width(4);
        p.set_byte_enable_ptr(nullptr);
        p.set_dmi_allowed(false);
        p.set_response_status(tlm::TLM_INCOMPLETE_RESPONSE);
        socket->b_transport(p, delay);
        wait(delay);
        return p.is_response_error() ? 1 : 0;
    }
    static int read32(void *user, uint32_t address, uint32_t *value) {
        int error = static_cast<Host *>(user)->transfer(address, value, false);
        std::printf("ACCESS R %08x %08x %d\n", address, *value, error);
        return error;
    }
    static int write32(void *user, uint32_t address, uint32_t value) {
        int error = static_cast<Host *>(user)->transfer(address, &value, true);
        std::printf("ACCESS W %08x %08x %d\n", address, value, error);
        return error;
    }
    static int irq(void *user) { return static_cast<Host *>(user)->timer->level() ? 1 : 0; }
    static void idle(void *) { sc_core::wait(CYCLE); }
    static void note(void *, const char *name, uint32_t value) { std::printf("NOTE %s %08x\n", name, value); }
    void main() {
        app_platform platform{this, read32, write32, irq, idle, note};
        result = app_run(&platform, &config);
        for (uint32_t word = 0; word < 64; word++) {
            uint32_t value = 0;
            if (transfer(APP_MEM + 4 * word, &value, false)) { std::printf("CHECK_FAIL PLAT_BUS\n"); break; }
            std::printf("MEM %02x %08x\n", word, value);
        }
        done = true;
        sc_stop();
    }
};

int sc_main(int argc, char **argv) {
    if (argc != 8) {
        std::fprintf(stderr, "usage: irqs load seed race lead wait_limit cycle_limit\n");
        return 2;
    }
    Host host("host");
    Router router("router");
    Memory memory("memory");
    Timer timer("timer");
    host.socket.bind(router.socket);
    router.memory.bind(memory.socket);
    router.timer.bind(timer.socket);
    host.timer = &timer;
    host.config.irqs = std::stoul(argv[1]); host.config.load = std::stoul(argv[2]);
    host.config.seed = std::stoul(argv[3]); host.config.race = std::stoul(argv[4]);
    host.config.lead = std::stoul(argv[5]); host.config.wait_limit = std::stoul(argv[6]);
    sc_start(double(std::stoull(argv[7])) * CYCLE.to_double(), SC_PS);
    if (!host.done) {
        std::printf("CHECK_FAIL PLAT_TIMEOUT\n");
        std::fflush(stdout);
        return 1;
    }
    std::printf("RESULT app=%d cycles=%llu\nEND\n", host.result,
                static_cast<unsigned long long>(sc_time_stamp() / CYCLE));
    std::fflush(stdout);
    return 0;
}
