`timescale 1ns/1ps
module axis_tb;
 parameter DEPTH=2,MUTATION=0;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,s_valid=0,s_last=0,m_ready=0;
 reg [31:0] s_data=0;reg [3:0] s_keep=0;wire s_ready,m_valid,m_last;wire [31:0] m_data;wire [3:0] m_keep;
 axis_packet_fifo #(.DEPTH(DEPTH),.MUTATION(MUTATION)) dut(.*);
 integer fd,n,v[0:11],checks=0,accepted=0,delivered=0,packets=0,bytes=0,flushes=0,packet_beats=0;
 reg input_open=0,output_open=0,held=0,recovering=0;reg [36:0] old_output;reg [31:0] byte_mask;reg will_flush;string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 function [31:0] lane_mask(input [3:0] keep);
  begin for(integer lane=0;lane<4;lane=lane+1)lane_mask[8*lane+:8]={8{keep[lane]}};end
 endfunction
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,axis_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]);if(n!=12)$fatal(1,"bad row");
   will_flush=!v[0] && (dut.count!=0 || input_open || output_open);
   if(will_flush!==v[11][0])fail("AXIS_RESET");
   if(will_flush)begin flushes=flushes+1;recovering=1;if(dut.count!=0)$display("COVER reset/queued");if(output_open)$display("COVER reset/partial-output");end
   rst_n=v[0];s_valid=v[1];s_data=v[2];s_keep=v[3];s_last=v[4];m_ready=v[5];#1;
   if(s_ready!==v[6][0] || m_valid!==v[7][0])fail("AXIS_CONTROL");
   if(m_valid)begin
    if({m_keep,m_last}!=={v[9][3:0],v[10][0]})fail("AXIS_META");
    byte_mask=lane_mask(m_keep);if(((m_data^v[8])&byte_mask)!==32'b0)fail("AXIS_DATA");
   end
   if(!rst_n)begin held=0;input_open=0;output_open=0;packet_beats=0;end
   else begin
    if(held && (!m_valid || {m_last,m_keep,m_data}!==old_output))fail("AXIS_HOLD");
    held=m_valid&&!m_ready;old_output={m_last,m_keep,m_data};
    if(s_valid && s_ready)begin accepted=accepted+1;input_open=!s_last;end
    if(s_valid && !s_ready)$display("COVER handshake/source-stall");
    if(m_valid && !m_ready)$display("COVER handshake/sink-stall");
    if(s_valid && s_ready && m_valid && m_ready)$display("COVER handshake/simultaneous");
    if(m_valid && m_ready)begin
     delivered=delivered+1;output_open=!m_last;packet_beats=packet_beats+1;
     for(integer lane=0;lane<4;lane=lane+1)if(m_keep[lane])bytes=bytes+1;
     if(m_keep==15)$display("COVER keep/full");else if(m_keep==0)$display("COVER keep/null");else $display("COVER keep/partial");
     if(m_last)begin packets=packets+1;if(packet_beats==1)$display("COVER packet/single");else $display("COVER packet/multiple");packet_beats=0;if(recovering)begin $display("COVER reset/recovery");recovering=0;end end
    end
   end
   if(m_valid)$display("OBS AXIS cycle=%0d ready=%0d valid=1 data=%08x keep=%x last=%0d",checks,s_ready,m_data&lane_mask(m_keep),m_keep,m_last);
   else $display("OBS AXIS cycle=%0d ready=%0d valid=0",checks,s_ready);
   @(posedge clk);#1;checks=checks+1;@(negedge clk);
  end
  $display("COUNT accepted=%0d",accepted);$display("COUNT delivered=%0d",delivered);$display("COUNT packets=%0d",packets);$display("COUNT bytes=%0d",bytes);$display("COUNT flushes=%0d",flushes);
  $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
