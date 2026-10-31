// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Abstract command-level DRAM controller, deliberately not a DDR PHY.
module dram_controller #(parameter TRCD=2,TRP=2,TRAS=3,TWR=4,TRFC=5,CL=2,TREFI=24,MUTATION=0)(
 input wire clk,rst_n,req_valid,req_write,req_bank,input wire [1:0] req_row,req_col,
 input wire [31:0] req_data,output wire req_ready,
 output reg resp_valid, input wire resp_ready,output reg [31:0] resp_data,
 output reg [2:0] cmd,output reg cmd_bank,output reg [1:0] cmd_row,cmd_col,
 output reg [31:0] cmd_data,input wire read_valid,input wire [31:0] read_data
);
 localparam IDLE=0,ACCESS=1,WAIT_READ=2;
 reg [1:0] state;
 reg [1:0] opened;
 reg [1:0] row[0:1];
 integer col_wait[0:1],pre_wait[0:1],act_wait[0:1],quiet,age;
 reg saved_write,saved_bank;reg [1:0] saved_row,saved_col;reg [31:0] saved_data;
 wire unused_cl=^(32'(CL));
 assign req_ready=rst_n && state==IDLE && !resp_valid && age<TREFI && quiet==0;
 always @* begin
  cmd=0;cmd_bank=saved_bank;cmd_row=saved_row;cmd_col=saved_col;cmd_data=saved_data;
  if(MUTATION==4 && !saved_write)cmd_col=saved_col^2'd1;
  if(rst_n && quiet==0)begin
   if(state==IDLE && age>=TREFI)begin
    if(MUTATION==2)cmd=5;
    else if(opened[0])begin if(pre_wait[0]==0)begin cmd=4;cmd_bank=0;end end
    else if(opened[1])begin if(pre_wait[1]==0)begin cmd=4;cmd_bank=1;end end
    else if(act_wait[0]==0 && act_wait[1]==0)cmd=5;
   end else if(state==ACCESS)begin
    if(!opened[saved_bank])begin if(act_wait[saved_bank]==0)cmd=1;end
    else if(row[saved_bank]!=saved_row)begin
     if(pre_wait[saved_bank]==0 || MUTATION==3)cmd=4;
    end else if(col_wait[saved_bank]==0 || MUTATION==1)cmd=saved_write?3:2;
   end
  end
 end
 always @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;opened<=0;age<=0;quiet<=0;resp_valid<=0;resp_data<=0;
   saved_write<=0;saved_bank<=0;saved_row<=0;saved_col<=0;saved_data<=0;
   for(integer b=0;b<2;b=b+1)begin row[b]<=0;col_wait[b]<=0;pre_wait[b]<=0;act_wait[b]<=0;end
  end else begin
   age<=age+1;
   if(quiet>0)quiet<=quiet-1;
   for(integer b=0;b<2;b=b+1)begin
    if(col_wait[b]>0)col_wait[b]<=col_wait[b]-1;
    if(pre_wait[b]>0)pre_wait[b]<=pre_wait[b]-1;
    if(act_wait[b]>0)act_wait[b]<=act_wait[b]-1;
   end
   if(resp_valid && resp_ready)resp_valid<=0;
   if(req_valid && req_ready)begin
    saved_write<=req_write;saved_bank<=req_bank;saved_row<=req_row;saved_col<=req_col;saved_data<=req_data;state<=ACCESS;
   end
   if(state==WAIT_READ && read_valid)begin resp_data<=read_data;resp_valid<=1;state<=IDLE;end
   case(cmd)
    1:begin opened[cmd_bank]<=1;row[cmd_bank]<=cmd_row;col_wait[cmd_bank]<=TRCD-1;pre_wait[cmd_bank]<=TRAS-1;end
    2:state<=WAIT_READ;
    3:begin
     if(pre_wait[cmd_bank]<TWR-1)pre_wait[cmd_bank]<=TWR-1;
     resp_data<=0;resp_valid<=1;state<=IDLE;
    end
    4:begin opened[cmd_bank]<=0;act_wait[cmd_bank]<=TRP-1;end
    5:begin age<=0;quiet<=TRFC-1;end
    default:begin end
   endcase
  end
 end
endmodule
