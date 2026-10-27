`timescale 1ns/1ps
module clock_reset_tb;
 parameter MUTATION=0,STAGES=2,LATENCY=4;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
reg core_reset_n=0;
reg stop_req=0;
reg wake_req=0;
reg req_valid=0;
reg [7:0] req_data=0;
wire req_ready;
wire stopped;
wire clock_enabled;
wire reset_released;
wire [7:0] result;
wire [15:0] completed;
 integer fd,n,checks=0;reg [63:0] v[0:11];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
 clock_reset #(.MUTATION(MUTATION),.STAGES(STAGES),.LATENCY(LATENCY)) dut(.*);
reg had_stop=0,ever_stop=0,previous_enabled=0;reg [15:0] old_completed=0;integer work_edges=0,old_edges=0;
always @(posedge dut.work_clk)work_edges=work_edges+1;
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,clock_reset_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]);if(n!=12)$fatal(1,"bad row");
 if(!v[1] && core_reset_n && dut.remaining!=0)$display("COVER reset/active");
 rst_n=v[0];
core_reset_n=v[1];
stop_req=v[2];
wake_req=v[3];
req_valid=v[4];
req_data=v[5];
 #1;
 if(req_ready!==v[6][0:0])fail("CLOCK_CONTROL");
if(stopped!==v[7][0:0])fail("CLOCK_CONTROL");
if(clock_enabled!==v[8][0:0])fail("CLOCK_CONTROL");
if(reset_released!==v[9][0:0])fail("CLOCK_CONTROL");
if(result!==v[10][7:0])fail("CLOCK_DATA");
if(completed!==v[11][15:0])fail("CLOCK_DATA");

 if(checks>0 && work_edges-old_edges!=previous_enabled)fail("CLOCK_EDGE");
 previous_enabled=clock_enabled;
 if(stopped && !clock_enabled)begin
 $display("COVER clock/stopped");ever_stop=1;
 if(had_stop && work_edges!=old_edges)fail("CLOCK_EDGE");
 if(!core_reset_n)$display("COVER reset/assert-stopped");
 if(core_reset_n && !reset_released)$display("COVER reset/held-until-clock");
 end
 had_stop=stopped && !clock_enabled;old_edges=work_edges;
 if(!core_reset_n && dut.remaining!=0)$display("COVER reset/active");
 if(rst_n && !core_reset_n && req_valid)$display("COVER reset/active");
 if(req_valid && req_ready)$display("COVER request/accepted");
 if(completed!=old_completed && completed!=0)$display("COVER request/completed");old_completed=completed;
 if(stop_req && dut.remaining!=0)$display("COVER stop/drain");
 if(stop_req && req_valid && !req_ready)$display("COVER stop/blocked-request");
 if(ever_stop && req_ready)begin $display("COVER clock/resumed");ever_stop=0;end
 if(reset_released)$display("COVER reset/released");

 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
 endmodule
