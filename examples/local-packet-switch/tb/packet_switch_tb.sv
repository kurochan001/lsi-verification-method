`timescale 1ns/1ps
module packet_switch_tb;
 parameter WIDTH=8,MUTATION=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;reg [1:0] s_valid=0,s_last=0,s_dest=0,m_ready=0;
 reg [2*WIDTH-1:0] s_data=0;wire [1:0] s_ready,m_valid,m_last;wire [2*WIDTH-1:0] m_data;
 packet_switch #(.WIDTH(WIDTH),.MUTATION(MUTATION)) dut(.*);
 integer fd,n,checks=0,o,s,d;reg [63:0] v[0:9];string vectors,wave;
 reg [WIDTH:0] queue0[0:16383],queue1[0:16383];integer wr[0:1],rd[0:1];
 reg [1:0] stalled=0,held_last=0,held_dest=0;reg [2*WIDTH-1:0] held_data=0;
 integer source_route[0:1];reg [1:0] input_packet=0;reg pending=0;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
 initial begin
  wr[0]=0;wr[1]=0;rd[0]=0;rd[1]=0;source_route[0]=0;source_route[1]=0;
  if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,packet_switch_tb);fd=$fopen(vectors,"r");if(fd==0)$fatal(1,"missing input");repeat(2)@(negedge clk);
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9]);if(n!=10)$fatal(1,"bad row");
   rst_n=v[0][0];s_valid=v[1][1:0];s_last=v[2][1:0];s_dest=v[3][1:0];s_data=v[4][2*WIDTH-1:0];m_ready=v[5][1:0];#1;
   if(s_ready!==v[6][1:0] || m_valid!==v[7][1:0])fail("PACKET_FLOW");
   for(o=0;o<2;o=o+1)if(m_valid[o] && (m_last[o]!==v[8][o] || m_data[o*WIDTH+:WIDTH]!==v[9][o*WIDTH+:WIDTH]))fail("PACKET_DATA");
   if(!rst_n)begin
    if(pending)$display("COVER reset/packet");pending=0;input_packet=0;stalled=0;
    for(o=0;o<2;o=o+1)begin wr[o]=0;rd[o]=0;end
   end else begin
    for(s=0;s<2;s=s+1)if(stalled[s] && (!s_valid[s] || s_last[s]!==held_last[s] || s_dest[s]!==held_dest[s] || s_data[s*WIDTH+:WIDTH]!==held_data[s*WIDTH+:WIDTH]))fail("PACKET_SOURCE");
    stalled=s_valid & ~s_ready;held_last=s_last;held_dest=s_dest;held_data=s_data;
    if((&m_valid) && (&m_ready))$display("COVER output/parallel");
    if((&s_valid) && s_dest[0]==s_dest[1])$display("COVER arbitration/contention");
    for(o=0;o<2;o=o+1)begin
     if(dut.locked[o] && !s_valid[dut.owner[o]])$display("COVER packet/input-gap");
     if(m_valid[o] && !m_ready[o])begin
      if(m_last[o])$display("COVER output/tail-hold");else $display("COVER output/head-body-hold");
      if(!dut.locked[o])$display("COVER output/header-reservation");
     end
    end
    for(s=0;s<2;s=s+1)if(s_valid[s] && s_ready[s])begin
     d=input_packet[s]?source_route[s]:int'(s_dest[s]);
     if(input_packet[s] && s_dest[s]!=1'(d))$display("COVER route/body-ignored");
     if(!input_packet[s])begin
      if(s_last[s])$display("COVER packet/single");else $display("COVER packet/multiple");
     end
     if(wr[d]-rd[d]>=16384)fail("PACKET_CAPACITY");
     if(d==0)queue0[wr[d]%16384]={s_last[s],s_data[s*WIDTH+:WIDTH]};else queue1[wr[d]%16384]={s_last[s],s_data[s*WIDTH+:WIDTH]};
     wr[d]=wr[d]+1;source_route[s]=d;input_packet[s]=!s_last[s];
     if(s==0)$display("COVER input/zero");else $display("COVER input/one");
    end
    for(o=0;o<2;o=o+1)if(m_valid[o] && m_ready[o])begin
     if(rd[o]>=wr[o])fail("PACKET_UNEXPECTED");
     if(o==0)begin
      if({m_last[o],m_data[o*WIDTH+:WIDTH]}!==queue0[rd[o]%16384])fail("PACKET_SCOREBOARD");$display("COVER output/zero");
     end else begin
      if({m_last[o],m_data[o*WIDTH+:WIDTH]}!==queue1[rd[o]%16384])fail("PACKET_SCOREBOARD");$display("COVER output/one");
     end
     rd[o]=rd[o]+1;
    end
    pending=|input_packet;
   end
   @(posedge clk);#1;checks=checks+1;@(negedge clk);
  end
  if(pending || rd[0]!=wr[0] || rd[1]!=wr[1])fail("PACKET_UNDRAINED");
  $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
