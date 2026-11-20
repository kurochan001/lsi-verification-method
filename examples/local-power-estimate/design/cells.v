// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Zero-delay simulation models of the teaching cells. Simulation only: the flop and the latch
// start at 0 so that the activity file holds no unknown values.
`timescale 1ns/1ps
module BUF(input wire A, output wire Y);
    assign Y = A;
endmodule

module MUX2(input wire A, input wire B, input wire S, output wire Y);
    assign Y = S ? B : A;
endmodule

module DFF(input wire CLK, input wire D, output reg Q);
    initial Q = 1'b0;
    always @(posedge CLK) Q <= D;
endmodule

// Clock gate: the enable is latched while the clock is low, so the gated clock has no short pulse.
module ICG(input wire CLK, input wire EN, output wire GCLK);
    reg keep;
    initial keep = 1'b0;
    always @(CLK or EN) if (!CLK) keep = EN;
    assign GCLK = CLK & keep;
endmodule
