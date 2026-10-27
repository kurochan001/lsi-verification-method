// Two-tap signed fixed-point FIR; round nearest, ties away from zero, then saturate.
module fir2 #(parameter FRAC=4,LATENCY=1,MUTATION=0)(
 input wire clk,rst_n,in_valid,input wire signed [7:0] sample,c0,c1,
 output wire in_ready,output reg out_valid,input wire out_ready,
 output reg signed [7:0] result,output reg clipped
);
 reg signed [7:0] previous,saved_result;reg saved_clip,busy;integer remaining;
 integer accumulator,magnitude,rounded,quantized;
 assign in_ready=rst_n && !busy && !out_valid;
 always @*begin
  accumulator=(MUTATION==1 ? int'($unsigned(sample))*int'($unsigned(c0)) : int'($signed(sample))*int'($signed(c0)))+
              int'($signed(previous))*int'($signed(c1));
  magnitude=accumulator<0 ? -accumulator:accumulator;
  rounded=(magnitude+(MUTATION==2 ? 0:(1<<(FRAC-1))))>>FRAC;
  quantized=accumulator<0 ? -rounded:rounded;
 end
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin previous<=0;saved_result<=0;saved_clip<=0;busy<=0;remaining<=0;out_valid<=0;result<=0;clipped<=0;end
  else begin
   if(out_valid && out_ready)out_valid<=0;
   if(busy)begin
    if(remaining==0)begin out_valid<=1;result<=saved_result ^ (MUTATION==4 ? 8'b1:0);clipped<=saved_clip;busy<=0;end
    else remaining<=remaining-1;
   end
   if(in_valid && in_ready)begin
    previous<=sample;busy<=1;remaining<=LATENCY-1;
    saved_clip<=quantized>127 || quantized< -128;
    if(MUTATION==3)saved_result<=quantized;
    else if(quantized>127)saved_result<=127;
    else if(quantized< -128)saved_result<=-128;
    else saved_result<=quantized;
   end
  end
 end
endmodule
