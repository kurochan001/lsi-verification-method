// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
module pipeline(input clk, input din, output dout);
 wire q0,b0,b1;
 DFF u0(.CLK(clk),.D(din),.Q(q0));
 BUF delay0(.A(q0),.Y(b0));
 BUF delay1(.A(b0),.Y(b1));
 DFF u1(.CLK(clk),.D(b1),.Q(dout));
endmodule
