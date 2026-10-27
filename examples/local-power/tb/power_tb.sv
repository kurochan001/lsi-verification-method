`timescale 1ns/1ps
module power_tb;
 parameter MUTATION=0,LATENCY=2;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
 reg sleep_req=0;
 reg wake_req=0;
 reg retain=0;
 reg req_valid=0;
 reg [7:0] req_data=0;
 wire req_ready;
 wire power_good;
 wire isolate;
 wire clock_enable;
 wire sleep_ack;
 wire done;
 wire [7:0] result;
 power_island #(.MUTATION(MUTATION),.LATENCY(LATENCY)) dut(.*);integer accepted=0,completed=0,off_cycles=0;reg keep_seen=0;
 integer fd,n,v[0:12],checks=0;string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,power_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12]);
 if(n!=13)$fatal(1,"bad row");
 if(!v[0] && rst_n && (dut.state!=0 || dut.pending))$display("COVER reset/active");
 rst_n=v[0];
 sleep_req=v[1];
 wake_req=v[2];
 retain=v[3];
 req_valid=v[4];
 req_data=v[5];
 #1;
 if(isolate!==v[8][0:0])fail("POWER_ISOLATION");
 if(req_ready!==v[6][0:0] || power_good!==v[7][0:0] || clock_enable!==v[9][0:0] || sleep_ack!==v[10][0:0] || done!==v[11][0:0])fail("POWER_CONTROL");
 if(result!==v[12][7:0])fail("POWER_DATA");
 if(!power_good && (!isolate || result!==8'b0))fail("POWER_ISOLATION");
 if(rst_n && req_valid && req_ready)begin accepted=accepted+1;$display("COVER request/accepted");end
 if(done)begin completed=completed+1;$display("COVER request/completed");end
 if(sleep_ack)begin off_cycles=off_cycles+1;$display("COVER power/off");if(keep_seen)$display("COVER retention/keep");else $display("COVER retention/discard");end
 if(rst_n && sleep_req && !dut.state)keep_seen=retain;
 if(rst_n && sleep_req && dut.pending)$display("COVER power/drain");
 if(rst_n && dut.state==5)$display("COVER power/wake");
 if(rst_n && dut.state==6)$display("COVER power/restore");
 if(rst_n && isolate && power_good)$display("COVER power/isolate-before-off");
 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT accepted=%0d",accepted);$display("COUNT completed=%0d",completed);$display("COUNT off_cycles=%0d",off_cycles);
 $display("RESULT PASS checks=%0d",checks);$finish;end
endmodule
