/* File route: read the vector file, write the expected outputs of both channels.
 * usage: packet_cli INIT FAULT INSTANCES vectors expected summary
 * INSTANCES is 2, or 1 to create a model for channel 0 only (channel 1 must stay idle).
 * `expected` has one row per clock; `summary` has the block CRC of every packet
 * (computed again from the collected bytes) and the counters.
 * A vector row is "rst_n valid0 data0 last0 valid1 data1 last1"; data is 8 binary
 * digits and may contain x or z, which the model reads as 0 and counts. */
#include "packet_model.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int parse_data(const char *text, uint8_t *value, unsigned *unknown) {
    if (strlen(text) != 8) return 0;
    *value = 0;
    for (int index = 0; index < 8; index++) {
        char c = text[index];
        *value = (uint8_t)(*value << 1);
        if (c == '1') *value |= 1u;
        else if (c == 'x' || c == 'z') (*unknown)++;
        else if (c != '0') return 0;
    }
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 7) return 2;
    char *end;
    unsigned long init = strtoul(argv[1], &end, 0);
    if (*end || init > 0xfffful) return 2;
    long fault = strtol(argv[2], &end, 0);
    if (*end || fault < 0 || fault > 5) return 2;
    long instances = strtol(argv[3], &end, 0);
    if (*end || instances < 1 || instances > 2) return 2;
    pm_set_fault((int)fault);
    FILE *in = fopen(argv[4], "r");
    FILE *out = fopen(argv[5], "w");
    FILE *summary = fopen(argv[6], "w");
    if (!in || !out || !summary) return 2;
    packet_model idle = {0, 0, 0, 0, 0, 0, 0};
    packet_model *model[2] = {pm_new((uint16_t)init), instances == 2 ? pm_new((uint16_t)init) : &idle};
    if (!model[0] || !model[1]) return 2;
    static uint8_t bytes[2][512];
    size_t count[2] = {0, 0};
    unsigned unknown_valid = 0, unknown_idle = 0, rows = 0;
    int rst_n, valid[2], last[2];
    char data[2][16];
    int fields;
    while ((fields = fscanf(in, "%d %d %15s %d %d %15s %d", &rst_n, &valid[0], data[0], &last[0],
                            &valid[1], data[1], &last[1])) == 7) {
        for (int ch = 0; ch < 2; ch++) {
            uint8_t value;
            unsigned unknown = 0;
            if (!parse_data(data[ch], &value, &unknown)) return 2;
            if (rst_n && valid[ch]) unknown_valid += unknown;
            else unknown_idle += unknown;
            if (ch >= instances) {
                if (valid[ch]) return 2;
                continue;
            }
            pm_cycle(model[ch], rst_n, valid[ch], value, last[ch]);
            if (!rst_n) count[ch] = 0;
            else if (valid[ch]) {
                if (count[ch] < sizeof bytes[ch]) bytes[ch][count[ch]] = value;
                count[ch]++;
            }
        }
        fprintf(out, "%d %04x %02x %d %04x %02x\n", model[0]->done, model[0]->crc, model[0]->length,
                model[1]->done, model[1]->crc, model[1]->length);
        for (int ch = 0; ch < 2; ch++)
            if (rst_n && valid[ch] && last[ch]) {
                if (count[ch] <= sizeof bytes[ch])
                    fprintf(summary, "B %d %zu %04x\n", ch, count[ch], pm_block(bytes[ch], count[ch], (uint16_t)init));
                count[ch] = 0;
            }
        rows++;
    }
    if (fields != EOF || !rows) return 2;
    fprintf(summary, "COUNT rows=%u packets0=%u packets1=%u unknown_valid=%u unknown_idle=%u\n", rows,
            model[0]->packets, model[1]->packets, unknown_valid, unknown_idle);
    pm_free(model[0]);
    if (instances == 2) pm_free(model[1]);
    return fclose(out) || fclose(summary) ? 2 : 0;
}
