`timescale 1ns/1ps
module fair_arbiter #(parameter MUTATION=0)(
 input wire clk,rst_n,input wire [1:0] request,input wire enable,
 output wire [1:0] ready,grant,output reg [1:0] pending,output reg turn
);
 wire both=&pending;
 wire chosen=(MUTATION==1) ? 1'b0:turn;
 assign grant[0]=rst_n && enable && pending[0] && (!both || !chosen);
 assign grant[1]=rst_n && enable && pending[1] && (!both || chosen);
 assign ready=~pending|grant;
 always @(posedge clk)begin
  if(!rst_n)begin pending<=0;turn<=0;end
  else begin
   pending<=(pending & ~grant)|(request & ready);
   if(MUTATION==2 && !enable)pending[1]<=0;
   if(|grant)turn<=grant[0];
  end
 end
endmodule
