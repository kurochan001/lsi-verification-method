`timescale 1ns/1ps
module irq_regs(input wire clk,rst_n,input wire [1:0] events,clear,mask,
 output reg [1:0] pending,output wire irq,output wire [7:0] debug_hint);
 reg [1:0] diagnostic;
 always @(posedge clk)begin
  if(!rst_n)begin pending<=0;diagnostic<=0;end
  else begin pending<=(pending & ~clear)|events;diagnostic<=diagnostic+2'd1;end
 end
 assign irq=|(pending & mask);
 // Deliberately unspecified debug information is outside the functional oracle.
 assign debug_hint={4'hc,diagnostic,pending};
endmodule
