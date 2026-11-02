// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
module e2e_guard #(parameter integer DATA_ID=32'ha12f,MUTATION=0)(
 input wire clk,rst_n,flush,in_valid,out_ready,
 input wire [47:0] in_frame,
 output wire in_ready,
 output reg out_valid,
 output reg [15:0] out_data,
 output reg accepted,rejected,
 output reg [1:0] reject_code
);
 reg [7:0] next_counter;
 reg [7:0] crc;
 reg [1:0] reason;
 always @* begin
  crc=8'hff;
  for(integer i=47;i>=8;i=i-1)begin
   if(crc[7]^in_frame[i])crc=(crc<<1)^8'h1d;
   else crc=crc<<1;
  end
  crc=crc^8'hff;
  reason=0;
  if(crc!=in_frame[7:0] && MUTATION!=1)reason=1;
  else if(in_frame[47:32]!=16'(DATA_ID) && MUTATION!=2)reason=2;
  else if(in_frame[31:24]!=next_counter && MUTATION!=3)reason=3;
 end
 assign in_ready=rst_n && !flush && (MUTATION==4 || !out_valid || out_ready);
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin next_counter<=0;out_valid<=0;out_data<=0;accepted<=0;rejected<=0;reject_code<=0;end
  else if(flush)begin if(MUTATION!=5)next_counter<=0;out_valid<=0;out_data<=0;accepted<=0;rejected<=0;reject_code<=0;end
  else begin
   accepted<=0;rejected<=0;reject_code<=0;
   if(out_valid && out_ready)begin out_valid<=0;out_data<=0;end
   if(in_valid && in_ready)begin
    if(reason!=0)begin rejected<=1;reject_code<=reason;end
    else begin accepted<=1;out_valid<=1;out_data<=in_frame[23:8];next_counter<=next_counter+8'd1;end
   end
  end
 end
endmodule
