// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Simulation model of the fault site: a buffer whose path delay comes from the SDF file, with a
// fault that the bench selects through `kind` and `extra` of the instance.
//   0: no fault   1: stuck at 0   2: stuck at 1   3: slow to rise   4: slow to fall
// A slow node follows its input `extra` ns late in the slow direction only. If the input has
// gone back by then, the output does not move: a short pulse is swallowed, not shifted.
`timescale 1ns/1ps
module TFSITE(input A, output Y);
    integer kind;
    real extra;
    reg y;
    initial begin kind = 0; extra = 0; end
    always @(A) begin
        if ((kind == 3 && A === 1'b1) || (kind == 4 && A === 1'b0)) #(extra);
        y = A;
    end
    wire value = kind == 1 ? 1'b0 : kind == 2 ? 1'b1 : y;
    buf (Y, value);
    specify (A => Y) = (0, 0); endspecify
endmodule
