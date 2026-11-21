`timescale 1ns/1ps
// Real-number model of the capacitor DAC and the comparator.
//
// It keeps what decides the code and drops everything that takes time: the array holds the
// input charge exactly, the top plate jumps to its settled value, and the comparator has no
// offset, noise or delay.  Capacitor values are set from outside so that the same model can
// carry a mismatched array.
module sar_cdac_rnm #(parameter BITS = 6)(
    input  wire            sample,
    input  wire [BITS-1:0] dac_code,
    output wire            cmp
);
    real cap [0:BITS];      // farads are not needed: only ratios matter (attofarads here)
    real cp, vref_v, vin_v; // parasitic, reference and the input pin, set by the testbench
    real held_v, total, switched, top_v;
    integer k;

    initial begin
        for (k = 0; k <= BITS; k = k + 1) cap[k] = 0.0;
        cp = 0.0; vref_v = 0.0; vin_v = 0.0; held_v = 0.0; top_v = 0.0;
    end

    // The top switch opens at the end of the sample cycle and freezes the charge.
    always @(negedge sample) held_v = vin_v;

    always @* begin
        total = 0.0;
        switched = 0.0;
        for (k = 0; k <= BITS; k = k + 1) total = total + cap[k];
        for (k = 0; k < BITS; k = k + 1) if (dac_code[k]) switched = switched + cap[k];
        if (sample || total == 0.0) top_v = 0.0;
        else top_v = (-held_v * total + vref_v * switched) / (total + cp);
    end

    assign cmp = top_v < 0.0;
endmodule
