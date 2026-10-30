`timescale 1ns/1ps
module mbist_tb;
 parameter MUTATION=0,DEPTH=8;reg clk=0;always #5 clk=~clk;
 reg rst_n=0,start=0;wire busy,done,failed,req_valid,req_write,req_data;wire[$clog2(DEPTH)-1:0]fail_addr,req_addr;reg req_ready=0;reg memory[0:DEPTH-1];reg read_data;
 integer fault,victim,aggressor,kind,stall,operations,cycle,index,old_value,new_value,fd,n,checks=0;
 reg[4095:0]v[0:8];reg[7:0]operation;string vectors,wave;
 mbist #(.MUTATION(MUTATION),.DEPTH(DEPTH)) dut(.*);
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d ops=%0d",checks,operations);end endtask
 always @*begin index=(fault==3 && req_addr==victim)?aggressor:req_addr;read_data=(fault==1 && req_addr==victim)?kind[0]:memory[index];end
 // restart=1 starts again after a failing test without reset; start must clear the failure record.
 task run(input integer stop_early,input integer restart);
 begin operations=0;cycle=0;if(restart)fault=0;
 for(integer a=0;a<DEPTH;a=a+1)memory[a]=0;
 start=1;@(posedge clk);#1;@(negedge clk);start=0;
 while(!done && cycle<DEPTH*80)begin
 req_ready=stall==0 || cycle%stall!=0;start=!stop_early && cycle==DEPTH+1;#1; // start while busy must be ignored
 if(req_valid && req_ready)begin
 operation=v[8]>>(8*operations);
 if(req_addr!==operation[7:2] || req_write!==operation[1] || (req_write && req_data!==operation[0]))fail("MBIST_OP");
 end
 @(posedge clk);
 if(req_valid && req_ready)begin
 if(req_write)begin
 old_value=memory[index];new_value=req_data;
 if(fault==1 && req_addr==victim)new_value=kind;
 if(fault==2 && req_addr==victim && old_value==kind && req_data!=kind)new_value=old_value;
 memory[index]=new_value;
 if(fault==4 && req_addr==aggressor && old_value==0 && new_value==1)memory[victim]=!memory[victim];
 end operations=operations+1;
 end
 #1;@(negedge clk);cycle=cycle+1;
 if(stop_early && operations>=3)begin if(!busy)fail("MBIST_RESET");rst_n=0;#1;@(posedge clk);#1;@(negedge clk);disable run;end
 end
 start=0;if(!done)fail("MBIST_TIMEOUT");
 if(operations!=10*DEPTH)fail("MBIST_COUNT");
 if(restart && failed!==0)fail("MBIST_RESTART");
 if(!restart && failed!==v[6][0])fail("MBIST_STATUS");
 if(!restart && failed && fail_addr!==v[7][$clog2(DEPTH)-1:0])fail("MBIST_ADDRESS");
 repeat(3)@(negedge clk);if(!done || busy || req_valid)fail("MBIST_DONE"); // done holds; no requests after completion
 if(!restart)begin
 if(fault==0)$display("COVER fault/clean");if(fault==1 && kind==0)$display("COVER fault/stuck0");if(fault==1 && kind==1)$display("COVER fault/stuck1");
 if(fault==2 && kind==0)$display("COVER fault/transition0");if(fault==2 && kind==1)$display("COVER fault/transition1");if(fault==3)$display("COVER fault/alias");if(fault==4)$display("COVER fault/coupling");
 if(stall!=0)$display("COVER memory/stall");
 end end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");$dumpfile(wave);$dumpvars(0,mbist_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8]);if(n!=9)$fatal(1,"bad row");
 fault=v[0];victim=v[1];aggressor=v[2];kind=v[3];stall=v[4];rst_n=0;start=0;req_ready=0;repeat(2)@(negedge clk);rst_n=1;
 if(v[5])begin run(1,0);rst_n=1;$display("COVER reset/restart");end
 run(0,0);if(v[6][0])run(0,1);checks=checks+1;
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end endmodule
