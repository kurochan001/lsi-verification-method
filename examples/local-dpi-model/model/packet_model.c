/* Table-driven CRC-16, one table lookup per byte. The RTL and the Python
 * model shift one bit at a time, so the three do not share this code path. */
#include "packet_model.h"
#include <stdlib.h>

static int fault;
static uint16_t table[256];
static int table_fault = -1;
static packet_model shared; /* used only by fault 2 */

void pm_set_fault(int value) { fault = value; }
int pm_fault(void) { return fault; }

static void build_table(void) {
    uint16_t poly = fault == 1 ? 0x8005u : 0x1021u;
    for (unsigned index = 0; index < 256; index++) {
        uint16_t value = (uint16_t)(index << 8);
        for (int bit = 0; bit < 8; bit++)
            value = (uint16_t)((value & 0x8000u) ? (value << 1) ^ poly : value << 1);
        table[index] = value;
    }
    table_fault = fault;
}

uint16_t pm_step(uint16_t crc, uint8_t data) {
    if (table_fault != fault) build_table();
    return (uint16_t)((crc << 8) ^ table[((crc >> 8) ^ data) & 0xffu]);
}

static void clear(packet_model *model) {
    model->crc_state = model->init;
    if (fault != 3) model->length_state = 0;
    model->done = 0;
    model->crc = 0;
    model->length = 0;
}

packet_model *pm_new(uint16_t init) {
    packet_model *model = fault == 2 ? &shared : (packet_model *)malloc(sizeof(packet_model));
    if (!model) return NULL;
    model->init = init;
    model->length_state = 0;
    model->packets = 0;
    clear(model);
    return model;
}

void pm_free(packet_model *model) {
    if (model != &shared) free(model);
}

int pm_cycle(packet_model *model, int rst_n, int valid, uint8_t data, int last) {
    if (!rst_n) {
        clear(model);
        return 0;
    }
    model->done = valid && last;
    if (!valid && fault == 5 && model->length_state != 0xffu) model->length_state++;
    if (valid) {
        uint16_t next = pm_step(model->crc_state, data);
        uint8_t count = model->length_state == 0xffu ? 0xffu : (uint8_t)(model->length_state + 1u);
        if (last) {
            model->crc = next;
            model->length = count;
            model->crc_state = model->init;
            model->length_state = 0;
            model->packets++;
        } else {
            model->crc_state = next;
            model->length_state = count;
        }
    }
    return model->done;
}

uint16_t pm_block(const uint8_t *bytes, size_t count, uint16_t init) {
    uint16_t crc = init;
    size_t end = fault == 4 && count ? count - 1 : count;
    for (size_t index = 0; index < end; index++) crc = pm_step(crc, bytes[index]);
    return crc;
}
