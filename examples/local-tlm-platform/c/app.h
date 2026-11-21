#ifndef TLM_PLATFORM_APP_H
#define TLM_PLATFORM_APP_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

/* The memory map both platforms implement. */
enum {
    APP_MEM = 0x0000,      /* 64 words */
    APP_TIMER = 0x1000,
    APP_LOAD = APP_TIMER + 0x00,
    APP_CTRL = APP_TIMER + 0x04,    /* bit0 enable, bit1 interrupt enable */
    APP_STATUS = APP_TIMER + 0x08,  /* bit0 pending, bit1 overrun; write 1 to clear */
    APP_COUNT = APP_TIMER + 0x0c,   /* cycles left before the next expiry */
    APP_EXPIRED = APP_TIMER + 0x10, /* expiries since the timer was enabled, 8 bits */
    APP_UNMAPPED = 0x2000
};

enum { APP_OK = 0, APP_BUS_ERROR = -1, APP_TIMEOUT = -2 };

/* What a platform gives the driver. read32/write32 return 0, or nonzero on a bus error. */
typedef struct {
    void *user;
    int (*read32)(void *, uint32_t, uint32_t *);
    int (*write32)(void *, uint32_t, uint32_t);
    int (*irq)(void *);
    void (*idle)(void *);
    void (*note)(void *, const char *, uint32_t);
} app_platform;

typedef struct {
    uint32_t irqs;       /* interrupts to handle, 1..16 */
    uint32_t load;       /* timer reload value */
    uint32_t seed;       /* table pattern */
    uint32_t race;       /* 1: time the acknowledge to land on the next expiry */
    uint32_t lead;       /* bus cycles from a read to the next write taking effect */
    uint32_t wait_limit; /* idle cycles allowed while waiting for one interrupt */
} app_config;

uint32_t app_pattern(uint32_t seed, uint32_t index);
int app_run(const app_platform *, const app_config *);

#ifdef __cplusplus
}
#endif
#endif
