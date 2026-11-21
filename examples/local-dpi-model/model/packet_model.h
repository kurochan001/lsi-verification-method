/* Cycle-level C reference model of packet_sum. Plain C, also valid as C++. */
#ifndef PACKET_MODEL_H
#define PACKET_MODEL_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct packet_model {
    uint16_t init;
    uint16_t crc_state;
    uint8_t length_state;
    int done;          /* output ports after the last clock edge */
    uint16_t crc;
    uint8_t length;
    unsigned packets;
} packet_model;

/* Deliberate model faults for the negative tests; 0 is the correct model. */
void pm_set_fault(int fault);
int pm_fault(void);

uint16_t pm_step(uint16_t crc, uint8_t data);
packet_model *pm_new(uint16_t init);
void pm_free(packet_model *model);
/* One rising clock edge. Returns the new value of `done`. */
int pm_cycle(packet_model *model, int rst_n, int valid, uint8_t data, int last);
uint16_t pm_block(const uint8_t *bytes, size_t count, uint16_t init);

#ifdef __cplusplus
}
#endif
#endif
