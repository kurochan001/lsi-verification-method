`timescale 1ns/1ps
module dsp_tb;
 parameter FRAC=4,LATENCY=1,MUTATION=0,CHECK_EXPECTATIONS=1;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,in_valid=0,out_ready=0;
 reg signed [7:0] sample=0,c0=0,c1=0;wire in_ready,out_valid,clipped;wire signed [7:0] result;
 fir2 #(.FRAC(FRAC),.LATENCY(LATENCY),.MUTATION(MUTATION)) dut(.*);
 integer fd,n,v[0:9],checks=0,accepted=0,completed=0,clips=0,previous=0,acc,mag;
 bit held=0,invalid_x=0,active_x=0,injected=0;reg [8:0] old_output;string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 initial begin
  invalid_x=$test$plusargs("INVALID_X");active_x=$test$plusargs("ACTIVE_X");
  if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,dsp_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9]);if(n!=10)$fatal(1,"bad row");
   if(!v[0] && rst_n && (dut.busy || out_valid))$display("COVER reset/pending");
   rst_n=v[0];in_valid=v[1];sample=v[2];c0=v[3];c1=v[4];out_ready=v[5];
   if(invalid_x && !in_valid)begin sample='x;c0='x;c1='x;end
   if(active_x && in_valid && v[6]!=0 && c0!=0 && !injected)begin sample='x;injected=1;end
   #1;
   if(CHECK_EXPECTATIONS)begin
    if(in_ready!==v[6][0] || out_valid!==v[7][0])fail("DSP_CONTROL");
    if(out_valid && {clipped,result}!=={v[9][0],v[8][7:0]})fail("DSP_DATA");
   end
   if(!rst_n)begin previous=0;held=0;end
   else begin
    if(held && (!out_valid || {clipped,result}!==old_output))fail("DSP_HOLD");
    held=out_valid&&!out_ready;old_output={clipped,result};
    if(in_valid && in_ready)begin
     accepted=accepted+1;acc=$signed(sample)*$signed(c0)+previous*$signed(c1);mag=acc<0 ? -acc:acc;previous=$signed(sample);
     if((mag% (1<<FRAC))==(1<<(FRAC-1)))$display("COVER rounding/tie");
     if((mag% (1<<FRAC))>(1<<(FRAC-1)))$display("COVER rounding/up");
     if(c1!=0)$display("COVER fir/history");
    end
    if(out_valid && !out_ready)$display("COVER handshake/stall");
    if(out_valid && out_ready)begin
     completed=completed+1;if(clipped)begin clips=clips+1;if(result[7])$display("COVER saturation/low");else $display("COVER saturation/high");end
     if(result==0)$display("COVER result/zero");else if(result[7])$display("COVER result/negative");else $display("COVER result/positive");
    end
   end
   if(out_valid)$display("OBS DSP cycle=%0d ready=%0d valid=1 data=%02x clipped=%0d",checks,in_ready,result,clipped);
   else $display("OBS DSP cycle=%0d ready=%0d valid=0",checks,in_ready);
   @(posedge clk);#1;checks=checks+1;@(negedge clk);
  end
  $display("COUNT accepted=%0d",accepted);$display("COUNT completed=%0d",completed);$display("COUNT clipped=%0d",clips);
  $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
