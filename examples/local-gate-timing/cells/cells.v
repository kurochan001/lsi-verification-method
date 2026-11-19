// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Simulation models of the teaching cells. The delays in the specify blocks are zero: the SDF file
// replaces them. Icarus Verilog 14 annotates path delays but has no $setup or $hold, so the flops
// check their own data pin. TSETUP and THOLD are zero unless the bench sets them from the SDF file.
`timescale 1ns/1ps
package timing_pkg;
    int violations = 0;
    function automatic void violation();
        violations = violations + 1;
    endfunction
endpackage

module BUF(input A, output Y);
    buf (Y, A);
    specify (A => Y) = (0, 0); endspecify
endmodule

module CKDLY(input A, output Y);
    buf (Y, A);
    specify (A => Y) = (0, 0); endspecify
endmodule

module INV(input A, output Y);
    not (Y, A);
    specify (A => Y) = (0, 0); endspecify
endmodule

module NAND2(input A, input B, output Y);
    nand (Y, A, B);
    specify (A => Y) = (0, 0); (B => Y) = (0, 0); endspecify
endmodule

module NOR2(input A, input B, output Y);
    nor (Y, A, B);
    specify (A => Y) = (0, 0); (B => Y) = (0, 0); endspecify
endmodule

module XOR2(input A, input B, output Y);
    xor (Y, A, B);
    specify (A => Y) = (0, 0); (B => Y) = (0, 0); endspecify
endmodule

// A data change closer than TSETUP before the clock edge, or closer than THOLD after it, makes the
// output X, as the notifier of a library model would. A change at time zero is start-up, not data.
module DFF(input CLK, input D, output Q);
    parameter real TSETUP = 0, THOLD = 0;
    reg q;
    realtime changed, clocked;
    initial begin changed = -1; clocked = -1; end
    buf (Q, q);
    always @(posedge CLK) begin
        if (TSETUP > 0 && changed >= 0 && $realtime - changed < TSETUP) begin
            $display("TIMING setup %m at %0t", $realtime);
            timing_pkg::violation();
            q <= 1'bx;
        end else q <= D;
        clocked = $realtime;
    end
    always @(D) begin
        if (THOLD > 0 && clocked >= 0 && $realtime - clocked < THOLD) begin
            $display("TIMING hold %m at %0t", $realtime);
            timing_pkg::violation();
            q <= 1'bx;
        end
        changed = $realtime;
    end
    specify (posedge CLK => (Q : D)) = (0, 0); endspecify
endmodule

// With enable. The data pin is checked only while E is 1, like a conditional check in a library:
// with E at 0 the flop keeps its value, whatever D does. E itself is always checked.
module DFFE(input CLK, input D, input E, output Q);
    parameter real TSETUP = 0, THOLD = 0;
    reg q, taken;
    realtime changed, enabled, clocked;
    initial begin changed = -1; enabled = -1; clocked = -1; taken = 0; end
    buf (Q, q);
    always @(posedge CLK) begin
        taken = E === 1'b1;
        if (TSETUP > 0 && ((enabled >= 0 && $realtime - enabled < TSETUP) ||
                           (E !== 1'b0 && changed >= 0 && $realtime - changed < TSETUP))) begin
            $display("TIMING setup %m at %0t", $realtime);
            timing_pkg::violation();
            q <= 1'bx;
        end else if (E === 1'b1) q <= D;
        else if (E !== 1'b0) q <= 1'bx;
        clocked = $realtime;
    end
    always @(D) begin
        if (THOLD > 0 && taken && clocked >= 0 && $realtime - clocked < THOLD) begin
            $display("TIMING hold %m at %0t", $realtime);
            timing_pkg::violation();
            q <= 1'bx;
        end
        changed = $realtime;
    end
    always @(E) begin
        if (THOLD > 0 && clocked >= 0 && $realtime - clocked < THOLD) begin
            $display("TIMING hold %m at %0t", $realtime);
            timing_pkg::violation();
            q <= 1'bx;
        end
        enabled = $realtime;
    end
    specify (posedge CLK => (Q : D)) = (0, 0); endspecify
endmodule
