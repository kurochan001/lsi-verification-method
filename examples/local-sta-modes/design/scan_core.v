// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Hand-written netlist for the teaching library: four mux-scan flops on clk, one plain flop on aclk.
module scan_core(input clk, input aclk, input scan_enable, input scan_in, input din,
                 output dout, output aout, output scan_out);
 wire d0,d1,d2,d3,q0,q1,q2,q3,qa;
 wire c0,c1,c2,s1,h1,h2,h3;
 // Functional data: din -> f0 -> three buffers -> f1 -> one buffer -> f2 -> dout.
 // Scan chain: scan_in -> f0 -> f1 -> f2 -> f3 -> scan_out, each link through a hold buffer.
 MUX2 m0(.A(din),.B(scan_in),.S(scan_enable),.Y(d0));
 DFF f0(.CLK(clk),.D(d0),.Q(q0));
 BUF logic0(.A(q0),.Y(c0));
 BUF logic1(.A(c0),.Y(c1));
 BUF logic2(.A(c1),.Y(c2));
 BUF hold1(.A(q0),.Y(h1));
 MUX2 m1(.A(c2),.B(h1),.S(scan_enable),.Y(d1));
 DFF f1(.CLK(clk),.D(d1),.Q(q1));
 BUF stage1(.A(q1),.Y(s1));
 BUF hold2(.A(q1),.Y(h2));
 MUX2 m2(.A(s1),.B(h2),.S(scan_enable),.Y(d2));
 DFF f2(.CLK(clk),.D(d2),.Q(q2));
 BUF outbuf(.A(q2),.Y(dout));
 // The other clock domain: f2 -> ga, and ga -> f3 (functional input of the last scan flop).
 DFF ga(.CLK(aclk),.D(q2),.Q(qa));
 BUF aoutbuf(.A(qa),.Y(aout));
 BUF hold3(.A(q2),.Y(h3));
 MUX2 m3(.A(qa),.B(h3),.S(scan_enable),.Y(d3));
 DFF f3(.CLK(clk),.D(d3),.Q(q3));
 BUF scanbuf(.A(q3),.Y(scan_out));
endmodule
