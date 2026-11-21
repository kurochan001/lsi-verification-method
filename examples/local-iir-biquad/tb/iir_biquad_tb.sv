`timescale 1ns/1ps
// Vector-driven bench. Every row carries the inputs of one clock and the outputs the integer
// model expects before the edge. Expected values come from run.py; nothing is recomputed here
// except the conditions of the COVER lines and the counters.
module iir_biquad_tb;
 parameter FRAC=14,ROUND=1,SAT=1,MUTATION=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,clear=0,cfg_we=0,in_valid=0,out_ready=0;reg [2:0] cfg_addr=0;
 reg signed [15:0] cfg_data=0;reg signed [23:0] sample=0;
 wire in_ready,out_valid,ovf_pos,ovf_neg;wire signed [23:0] result;
 iir_biquad #(.FRAC(FRAC),.ROUND(ROUND),.SAT(SAT),.MUTATION(MUTATION)) dut(.*);
 integer fd,n,v[0:13],checks=0,accepted=0,completed=0,over_pos=0,over_neg=0,limit_nonzero=0,osc_large=0;
 integer magnitude;
 bit held=0,previous_accept=0;reg [25:0] old_output;string vectors,wave;
 wire [47:0] fraction=dut.acc & ((48'd1<<FRAC)-48'd1);
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d",checks);end endtask
 initial begin #50000000;$display("CHECK_FAIL IIR_TIMEOUT");$fatal(1,"bench did not finish");end
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,iir_biquad_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13]);
   if(n!=14)$fatal(1,"bad row");
   if(!v[0] && rst_n && out_valid)$display("COVER reset/pending");
   rst_n=v[0][0];clear=v[1][0];cfg_we=v[2][0];cfg_addr=v[3][2:0];cfg_data=v[4][15:0];in_valid=v[5][0];sample=v[6][23:0];out_ready=v[7][0];
   #1;
   if(in_ready!==v[9][0] || out_valid!==v[10][0])fail("IIR_CONTROL");
   if(out_valid && result!==v[11][23:0])fail("IIR_DATA");
   if(out_valid && {ovf_pos,ovf_neg}!=={v[12][0],v[13][0]})fail("IIR_FLAG");
   if(!rst_n)begin held=0;previous_accept=0;end
   else begin
    if(held && !clear && (out_valid!==1'b1 || {ovf_pos,ovf_neg,result}!==old_output))fail("IIR_HOLD");
    if(cfg_we)begin
     if(cfg_addr>3'd4)$display("COVER coef/ignored-address");
     else if(dut.y1!==24'sd0 || dut.y2!==24'sd0)$display("COVER coef/rewrite");
     if(in_valid && in_ready)$display("COVER coef/write-with-accept");
    end
    if(clear)begin
     if(dut.y1!==24'sd0 || dut.y2!==24'sd0)$display("COVER state/clear");
     if(in_valid)$display("COVER clear/offer");
    end
    if(in_ready && !in_valid)$display("COVER handshake/idle");
    if(in_valid && !in_ready && !clear)$display("COVER handshake/held-offer");
    if(out_valid && !out_ready)$display("COVER handshake/stall");
    if(in_valid && in_ready)begin
     accepted=accepted+1;
     if(previous_accept)$display("COVER handshake/back-to-back");
     if(fraction==(48'd1<<(FRAC-1)))$display("COVER rounding/tie");
     if(dut.acc[47] && fraction!=48'd0)$display("COVER rounding/negative");
     if((dut.coef[3]!==16'sd0 || dut.coef[4]!==16'sd0) && (dut.y1!==24'sd0 || dut.y2!==24'sd0))$display("COVER feedback/active");
    end
    previous_accept=in_valid && in_ready;
    if(out_valid && out_ready)begin
     completed=completed+1;magnitude=result[23] ? -result:result;
     if(ovf_pos)begin over_pos=over_pos+1;$display("COVER overflow/positive");end
     if(ovf_neg)begin over_neg=over_neg+1;$display("COVER overflow/negative");end
     if(!ovf_pos && result===24'sh7fffff)$display("COVER overflow/exact-high");
     if(!ovf_neg && result===24'sh800000)$display("COVER overflow/exact-low");
     if(v[8]==1)begin $display("COVER limit/zero-input-tail");if(result!==24'sd0)limit_nonzero=limit_nonzero+1;end
     if(v[8]==2)begin $display("COVER overflow/zero-input-tail");if(magnitude>=1048576)osc_large=osc_large+1;end
     if(v[8]==3)$display("COVER impulse/sample");
     $display("OBS IIR n=%0d phase=%0d y=%0d",completed,v[8],result);
    end
    held=out_valid && !out_ready && !clear;old_output={ovf_pos,ovf_neg,result};
   end
   @(posedge clk);#1;checks=checks+1;@(negedge clk);
  end
  $display("COUNT accepted=%0d",accepted);$display("COUNT completed=%0d",completed);
  $display("COUNT overflow_pos=%0d",over_pos);$display("COUNT overflow_neg=%0d",over_neg);
  $display("COUNT limit_tail_nonzero=%0d",limit_nonzero);$display("COUNT osc_tail_large=%0d",osc_large);
  $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
