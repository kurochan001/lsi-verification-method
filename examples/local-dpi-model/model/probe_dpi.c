/* Type-mapping probe for tb/dpi_probe_tb.sv. */
#include "svdpi.h"
#include <stdlib.h>
#include <string.h>
#ifdef __cplusplus
extern "C" {
#endif

extern void probe_note(int value);
extern void probe_task(int value);

signed char probe_byte(signed char value) { return (signed char)(value - 1); }
unsigned short probe_shortint(unsigned short value) { return (unsigned short)(value + 1u); }
int probe_int(int value) { return -value; }
long long probe_longint(long long value) { return value * 3; }
double probe_real(double value) { return value / 4.0; }

/* bit [7:0] arrives as one 32-bit word, bit [39:0] as two; unused upper bits are 0. */
void probe_bit(const svBitVecVal *narrow, const svBitVecVal *wide, svBitVecVal *out) {
    out[0] = wide[0] ^ narrow[0];
    out[1] = wide[1];
}

/* logic [7:0]: aval holds the value, bval marks X/Z. Returns the unknown-bit count
 * and answers with 4'bxxxx in the upper half. */
int probe_logic(const svLogicVecVal *in, svLogicVecVal *out) {
    unsigned unknown = in[0].bval & 0xffu;
    int count = 0;
    for (; unknown; unknown &= unknown - 1) count++;
    out[0].aval = 0x0fu;
    out[0].bval = 0xf0u;
    return count;
}

int probe_string(const char *text) { return (int)strlen(text); }

void *probe_handle_new(int value) {
    int *cell = (int *)malloc(sizeof(int));
    if (cell) *cell = value;
    return cell;
}
int probe_handle_take(void *handle) {
    int value = *(int *)handle;
    free(handle);
    return value;
}

/* Sum and element count of an unpacked byte array of any declared range. */
int probe_open(const svOpenArrayHandle bytes) {
    int sum = 0;
    for (int index = svLow(bytes, 1); index <= svHigh(bytes, 1); index++)
        sum += *(const unsigned char *)svGetArrElemPtr1(bytes, index);
    return sum * 1000 + svSize(bytes, 1);
}

/* context: looks up its calling scope and calls back into SystemVerilog. */
int probe_context(int value) {
    const char *name = svGetNameFromScope(svGetScope());
    probe_note(value);
    probe_note(value);
    return (int)strlen(name);
}
int probe_import_task(int value) {
    probe_task(value);
    return 0;
}

#ifdef __cplusplus
}
#endif
