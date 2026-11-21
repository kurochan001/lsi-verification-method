/* DPI-C layer between the SystemVerilog testbench and packet_model.c.
 * Verilator compiles this file as C++, so it stays in the common subset. */
#include "packet_model.h"
#include "svdpi.h"
#include <string.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Exported by tb/dpi_tb.sv; only a context import may call it. */
extern void dpi_note_packet(unsigned int length);

void dpi_set_fault(int fault) { pm_set_fault(fault); }

/* pure: the result depends on the arguments alone. The lookup table inside is a
 * cache of constants; the fault hook of the negative tests is the one exception. */
unsigned short dpi_crc_step(unsigned short crc, unsigned char data) { return pm_step(crc, data); }

void *dpi_new(unsigned int init) { return pm_new((uint16_t)init); }
void dpi_free(void *handle) { pm_free((packet_model *)handle); }

/* 4-state input, 2-state outputs. Returns the number of unknown data bits. */
int dpi_cycle(void *handle, svBit rst_n, svBit valid, const svLogicVecVal *data, svBit last,
              svBit *done, svBitVecVal *crc, unsigned char *length) {
    packet_model *model = (packet_model *)handle;
    unsigned unknown = data[0].bval & 0xffu;
    int count = 0;
    for (; unknown; unknown &= unknown - 1) count++;
    /* Unknown bits are read as 0, as the file route does. The caller must flag them. */
    pm_cycle(model, rst_n, valid, (uint8_t)(data[0].aval & ~data[0].bval & 0xffu), last);
    *done = (svBit)model->done;
    crc[0] = model->crc;
    *length = model->length;
    if (model->done) dpi_note_packet(model->length);
    return count;
}

/* Open array: the same function accepts unpacked byte arrays of any size. */
int dpi_block(const svOpenArrayHandle bytes, unsigned int count, unsigned int init) {
    uint8_t copy[512];
    if (svDimensions(bytes) != 1 || count > (unsigned int)svSize(bytes, 1) || count > sizeof copy) return -1;
    for (unsigned int index = 0; index < count; index++)
        copy[index] = *(const uint8_t *)svGetArrElemPtr1(bytes, svLow(bytes, 1) + (int)index);
    return pm_block(copy, count, (uint16_t)init);
}

#ifdef __cplusplus
}
#endif
