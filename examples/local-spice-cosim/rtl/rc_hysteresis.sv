// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ps/1ps
module rc_hysteresis #(parameter integer ADC_BITS=8,MUTATION=0)(
 input wire clk,rst_n,enable,
 input wire [ADC_BITS-1:0] adc,low_code,high_code,
 output reg drive
);
 localparam integer EXT=ADC_BITS+1;
 wire [EXT-1:0] adjusted_low={1'b0,low_code}+EXT'(MUTATION==1 ? 8:0);
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)drive<=0;
  else if(!enable && MUTATION!=2)drive<=0;
  else if({1'b0,adc}<=adjusted_low)drive<=1;
  else if(adc>=high_code)drive<=0;
 end
endmodule
