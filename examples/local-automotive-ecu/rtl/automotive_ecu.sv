// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
module automotive_ecu #(
 parameter integer DATA_ID=32'ha12f,WINDOW_MIN=3,WINDOW_MAX=9,FRESH_MAX=13,MUTATION=0
)(
 input wire clk,rst_n,arm,disarm,ack,recover,permit,external_fault,service,in_valid,
 input wire [47:0] in_frame,
 output wire in_ready,enabled,faulted,pending,frame_ok,frame_reject,
 output wire [1:0] frame_code,
 output reg [15:0] drive_command,
 output reg [4:0] cause,
 output reg irq,applied,cancelled
);
 localparam [1:0] OFF=0,RUN=1,FAULT=2;
 reg [1:0] state;
 integer wd_age,fresh_age;
 reg [4:0] events;
 wire guard_ready,guard_valid;
 wire [15:0] guard_data;
 wire flush=state!=RUN || disarm || events!=0;
 wire consume=state==RUN && !disarm && events==0;
 e2e_guard #(.DATA_ID(DATA_ID)) guard(
  .clk(clk),.rst_n(rst_n),.flush(flush),.in_valid(in_valid && consume),.in_frame(in_frame),
  .out_ready(consume),.in_ready(guard_ready),.out_valid(guard_valid),.out_data(guard_data),
  .accepted(frame_ok),.rejected(frame_reject),.reject_code(frame_code)
 );
 assign in_ready=guard_ready && consume;
 assign enabled=rst_n && state==RUN;
 assign faulted=state==FAULT;
 assign pending=guard_valid;
 always @* begin
  events=external_fault ? 5'b00001:5'b00000;
  if(state==RUN)begin
   if(service && wd_age+1<WINDOW_MIN && MUTATION!=1)events[1]=1;
   if(!service && (MUTATION==2 ? wd_age+1>WINDOW_MAX:wd_age+1>=WINDOW_MAX))events[2]=1;
   if(!guard_valid && fresh_age+1>=FRESH_MAX)events[3]=1;
   if(guard_valid && guard_data>16'd1000)events[4]=1;
  end
 end
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state<=OFF;wd_age<=0;fresh_age<=0;drive_command<=0;cause<=0;irq<=0;applied<=0;cancelled<=0;end
  else begin
   applied<=0;cancelled<=0;
   if(ack)irq<=0;
   if(events!=0)begin
    state<=FAULT;cause<=cause|events;irq<=1;drive_command<=0;wd_age<=0;fresh_age<=0;
    cancelled<=guard_valid;
    if(MUTATION==4 && guard_valid)begin drive_command<=guard_data;applied<=1;end
   end else if(state==FAULT)begin
    if((recover && permit) || (MUTATION==5 && ack))begin state<=OFF;cause<=0;irq<=0;end
   end else if(disarm && state==RUN)begin
    state<=OFF;drive_command<=0;wd_age<=0;fresh_age<=0;cancelled<=guard_valid;
   end else if(state==OFF)begin
    if(arm)begin state<=RUN;drive_command<=0;wd_age<=0;fresh_age<=0;end
   end else begin
    if(service)wd_age<=0;else wd_age<=wd_age+1;
    if(guard_valid)begin drive_command<=guard_data;applied<=1;fresh_age<=0;end
    else if(MUTATION==3 && frame_reject)fresh_age<=0;
    else fresh_age<=fresh_age+1;
   end
  end
 end
endmodule
