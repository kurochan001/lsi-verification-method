`timescale 1ns/1ps
module replay_tb;
 parameter DEPTH=2,MUTATION=0;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,valid=0,ready=0;reg[3:0]data=0;
 wire gi,gv,oi,ov;wire[3:0]gd,od;wire[$clog2(DEPTH):0] gc,oc;wire[4*DEPTH-1:0]gcontents,ocontents;wire[$clog2(DEPTH)-1:0]head,tail;
 fifo_gold #(.DEPTH(DEPTH),.WIDTH(4)) gold(clk,rst_n,valid,ready,data,gi,gv,gd,gc,gcontents);
 fifo_optimized #(.DEPTH(DEPTH),.WIDTH(4),.MUTATION(MUTATION)) dut(clk,rst_n,valid,ready,data,oi,ov,od,oc,ocontents,head,tail);
 integer fd,n,checks=0,v[0:6];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");
 $dumpfile(wave);$dumpvars(0,replay_tb);fd=$fopen(vectors,"r");@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6]);if(n!=7)$fatal(1,"bad row");
 rst_n=v[0];valid=v[1];ready=v[2];data=v[3];#1;
 if(checks>0)begin
 if({gi,gv}!=={v[4][0],v[5][0]} || (gv && gd!==v[6][3:0]))fail("REPLAY_REFERENCE");
 if({gi,gv}!=={oi,ov})fail("ap_control");if(gv && gd!==od)fail("ap_data");
 end
 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
