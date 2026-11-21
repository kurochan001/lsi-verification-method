#include "app.h"

uint32_t app_pattern(uint32_t seed, uint32_t index)
{
    uint32_t x = seed * 0x9e3779b1u ^ index * 0x85ebca6bu ^ (index << 7);
    return x ^ (x >> 13);
}

#define CHECK(call) do { if (call) return APP_BUS_ERROR; } while (0)

int app_run(const app_platform *p, const app_config *c)
{
    void *u = p->user;
    uint32_t value = 0, acc = 0, k, n;

    /* A table the interrupt handler reads back. */
    for (k = 0; k < 16; k++)
        CHECK(p->write32(u, APP_MEM + 4 * k, app_pattern(c->seed, k)));

    /* Holes in the map must answer with a bus error: far away, one past the memory,
       one past the last timer register, one past the timer window, and misaligned. */
    {
        static const uint32_t holes[5] = { APP_UNMAPPED, APP_MEM + 0x100, APP_TIMER + 0x14, APP_TIMER + 0x20, APP_MEM + 2 };
        uint32_t errors = 0;
        for (k = 0; k < 5; k++) {
            value = 0;
            errors |= (uint32_t)(p->read32(u, holes[k], &value) != 0) << k;
        }
        CHECK(p->write32(u, APP_MEM + 0xc4, errors));
    }

    /* Masked interrupt: pending without the enable must not reach the line. A short
       period expires several times, so the second expiry sets overrun. The timer is
       stopped before the status is read, so the values do not depend on timing. */
    CHECK(p->write32(u, APP_LOAD, 5));
    CHECK(p->write32(u, APP_CTRL, 1));
    for (k = 0; k < 40; k++)
        p->idle(u);
    n = p->irq(u) != 0;
    p->note(u, "irq_level_masked", n);
    CHECK(p->write32(u, APP_MEM + 0xc8, n));
    CHECK(p->write32(u, APP_CTRL, 0));
    {
        uint32_t s1 = 0, s2 = 0, s3 = 0;
        CHECK(p->read32(u, APP_STATUS, &s1));
        CHECK(p->write32(u, APP_STATUS, 1));
        CHECK(p->read32(u, APP_STATUS, &s2));
        CHECK(p->write32(u, APP_STATUS, 2));
        CHECK(p->read32(u, APP_STATUS, &s3));
        CHECK(p->write32(u, APP_MEM + 0xcc, s1 | s2 << 4 | s3 << 8));
    }

    /* Periodic interrupts. Enabling again restarts the count and clears EXPIRED. */
    CHECK(p->write32(u, APP_LOAD, c->load));
    CHECK(p->write32(u, APP_CTRL, 3));
    for (k = 0; k < c->irqs; k++) {
        uint32_t status = 0, expired = 0, word = 0;
        for (n = 0; !p->irq(u); n++) {
            if (n >= c->wait_limit) {
                p->note(u, "timeout", k);
                return APP_TIMEOUT;
            }
            p->idle(u);
        }
        p->note(u, "irq", k);
        CHECK(p->read32(u, APP_STATUS, &status));
        CHECK(p->read32(u, APP_EXPIRED, &expired));
        if (c->race) {
            /* Wait until the acknowledge takes effect on the cycle of the next expiry,
               assuming every access takes `lead` cycles from read to write. */
            uint32_t left = 0, j;
            CHECK(p->read32(u, APP_COUNT, &left));
            for (j = 0; j + c->lead < left; j++)
                p->idle(u);
        }
        CHECK(p->write32(u, APP_STATUS, 1));
        CHECK(p->read32(u, APP_MEM + 4 * (k % 16), &word));
        acc += word ^ expired;
        CHECK(p->write32(u, APP_MEM + 0x40 + 4 * (k % 16), expired | status << 16));
        CHECK(p->write32(u, APP_MEM + 0x80 + 4 * (k % 16), acc));
    }
    CHECK(p->write32(u, APP_CTRL, 0));
    CHECK(p->write32(u, APP_MEM + 0xc0, acc));
    /* The configuration reads back as written, including the cleared enables. */
    CHECK(p->read32(u, APP_CTRL, &value));
    CHECK(p->write32(u, APP_MEM + 0xd0, value));
    CHECK(p->read32(u, APP_LOAD, &value));
    CHECK(p->write32(u, APP_MEM + 0xd4, value));
    return APP_OK;
}
