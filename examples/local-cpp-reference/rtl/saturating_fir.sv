// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
module saturating_fir #(
 parameter integer WIDTH=8,LATENCY=1,MUTATION=0
)(
 input wire clk,rst_n,in_valid,
 output wire in_ready,
 input wire signed [WIDTH-1:0] in_sample,
 output reg out_valid,
 input wire out_ready,
 output reg signed [WIDTH-1:0] out_sample
);
 localparam integer ACC_WIDTH=WIDTH+6;
 localparam signed [ACC_WIDTH-1:0] UPPER=ACC_WIDTH'((1<<(WIDTH-1))-1);
 localparam signed [ACC_WIDTH-1:0] LOWER=ACC_WIDTH'(-(1<<(WIDTH-1)));
 reg signed [WIDTH-1:0] h0,h1,saved;
 reg signed [ACC_WIDTH-1:0] x,a,b,sum,magnitude,rounded,quantized;
 integer remaining;
 assign in_ready=rst_n && remaining==0 && (!out_valid || out_ready);
 always @* begin
  x={{6{in_sample[WIDTH-1]}},in_sample};
  a={{6{h0[WIDTH-1]}},h0};b={{6{h1[WIDTH-1]}},h1};
  sum=(x<<<1)+x+(MUTATION==1 ? (a<<<1) : -(a<<<1))+b;
  magnitude=sum<0 ? -sum : sum;
  rounded=(magnitude+ACC_WIDTH'(2))>>>2;
  quantized=sum<0 ? -rounded : rounded;
  if(MUTATION==2 && sum<0)quantized=sum>>>2;
 end
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n)begin
   if(MUTATION!=4)begin h0<=0;h1<=0;end
   saved<=0;remaining<=0;out_valid<=0;out_sample<=0;
  end else begin
   if(out_valid && out_ready)out_valid<=0;
   if(MUTATION==3 && out_valid && !out_ready)out_sample<=out_sample^{{(WIDTH-1){1'b0}},1'b1};
   if(remaining>0)begin
    remaining<=remaining-1;
    if(remaining==1)begin out_sample<=saved;out_valid<=1;end
   end
   if(in_valid && in_ready)begin
    h1<=h0;h0<=in_sample;
    if(quantized>UPPER)saved<=WIDTH'(UPPER);
    else if(quantized<LOWER)saved<=WIDTH'(LOWER);
    else saved<=WIDTH'(quantized);
    if(LATENCY==1)begin
     if(quantized>UPPER)out_sample<=WIDTH'(UPPER);
     else if(quantized<LOWER)out_sample<=WIDTH'(LOWER);
     else out_sample<=WIDTH'(quantized);
     out_valid<=1;
    end else remaining<=LATENCY-1;
   end
  end
 end
endmodule
