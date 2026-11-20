// Latch-based clock gate: the enable is taken only while the clock is low, so a pulse is passed whole or not at all.
// MUTATION 1 gates with a plain AND; MUTATION 2 makes the latch transparent while the clock is high.
module clock_gate #(parameter integer MUTATION = 0) (
    input  wire clk,
    input  wire enable,
    output wire gclk
);
    reg enable_latched;
    wire transparent = (MUTATION == 2) ? clk : !clk;

    always_latch begin
        if (transparent)
            enable_latched = enable;
    end

    assign gclk = clk & ((MUTATION == 1) ? enable : enable_latched);
endmodule
