// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Hand-written netlists of one 8-bit register with a load enable, for the teaching library.

// The enable selects, in front of every flop, between the new value and the held one.
// The clock reaches all eight flops in every cycle.
module bank_plain(input clk, input en, input [7:0] d, output [7:0] q);
 wire clk_i;
 wire n0, n1, n2, n3, n4, n5, n6, n7;
 BUF ckbuf(.A(clk),.Y(clk_i));
 MUX2 m0(.A(q[0]),.B(d[0]),.S(en),.Y(n0));
 DFF r0(.CLK(clk_i),.D(n0),.Q(q[0]));
 MUX2 m1(.A(q[1]),.B(d[1]),.S(en),.Y(n1));
 DFF r1(.CLK(clk_i),.D(n1),.Q(q[1]));
 MUX2 m2(.A(q[2]),.B(d[2]),.S(en),.Y(n2));
 DFF r2(.CLK(clk_i),.D(n2),.Q(q[2]));
 MUX2 m3(.A(q[3]),.B(d[3]),.S(en),.Y(n3));
 DFF r3(.CLK(clk_i),.D(n3),.Q(q[3]));
 MUX2 m4(.A(q[4]),.B(d[4]),.S(en),.Y(n4));
 DFF r4(.CLK(clk_i),.D(n4),.Q(q[4]));
 MUX2 m5(.A(q[5]),.B(d[5]),.S(en),.Y(n5));
 DFF r5(.CLK(clk_i),.D(n5),.Q(q[5]));
 MUX2 m6(.A(q[6]),.B(d[6]),.S(en),.Y(n6));
 DFF r6(.CLK(clk_i),.D(n6),.Q(q[6]));
 MUX2 m7(.A(q[7]),.B(d[7]),.S(en),.Y(n7));
 DFF r7(.CLK(clk_i),.D(n7),.Q(q[7]));
endmodule

// A clock gate opens the clock only in the cycles that load. No multiplexers are needed.
module bank_gated(input clk, input en, input [7:0] d, output [7:0] q);
 wire clk_i, gclk;
 BUF ckbuf(.A(clk),.Y(clk_i));
 ICG gate(.CLK(clk_i),.EN(en),.GCLK(gclk));
 DFF r0(.CLK(gclk),.D(d[0]),.Q(q[0]));
 DFF r1(.CLK(gclk),.D(d[1]),.Q(q[1]));
 DFF r2(.CLK(gclk),.D(d[2]),.Q(q[2]));
 DFF r3(.CLK(gclk),.D(d[3]),.Q(q[3]));
 DFF r4(.CLK(gclk),.D(d[4]),.Q(q[4]));
 DFF r5(.CLK(gclk),.D(d[5]),.Q(q[5]));
 DFF r6(.CLK(gclk),.D(d[6]),.Q(q[6]));
 DFF r7(.CLK(gclk),.D(d[7]),.Q(q[7]));
endmodule

// A mistake: the clock gate was added, but its enable is the test bypass input, which the
// system holds at 1, and the multiplexers stayed. The function is unchanged; nothing is saved.
module bank_stuck(input clk, input en, input bypass, input [7:0] d, output [7:0] q);
 wire clk_i, gclk;
 wire n0, n1, n2, n3, n4, n5, n6, n7;
 BUF ckbuf(.A(clk),.Y(clk_i));
 ICG gate(.CLK(clk_i),.EN(bypass),.GCLK(gclk));
 MUX2 m0(.A(q[0]),.B(d[0]),.S(en),.Y(n0));
 DFF r0(.CLK(gclk),.D(n0),.Q(q[0]));
 MUX2 m1(.A(q[1]),.B(d[1]),.S(en),.Y(n1));
 DFF r1(.CLK(gclk),.D(n1),.Q(q[1]));
 MUX2 m2(.A(q[2]),.B(d[2]),.S(en),.Y(n2));
 DFF r2(.CLK(gclk),.D(n2),.Q(q[2]));
 MUX2 m3(.A(q[3]),.B(d[3]),.S(en),.Y(n3));
 DFF r3(.CLK(gclk),.D(n3),.Q(q[3]));
 MUX2 m4(.A(q[4]),.B(d[4]),.S(en),.Y(n4));
 DFF r4(.CLK(gclk),.D(n4),.Q(q[4]));
 MUX2 m5(.A(q[5]),.B(d[5]),.S(en),.Y(n5));
 DFF r5(.CLK(gclk),.D(n5),.Q(q[5]));
 MUX2 m6(.A(q[6]),.B(d[6]),.S(en),.Y(n6));
 DFF r6(.CLK(gclk),.D(n6),.Q(q[6]));
 MUX2 m7(.A(q[7]),.B(d[7]),.S(en),.Y(n7));
 DFF r7(.CLK(gclk),.D(n7),.Q(q[7]));
endmodule
