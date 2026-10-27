`timescale 1ns/1ps
module rtl_tb;
 parameter MUTATION=0,WAIT_CYCLES=0;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,psel=0,penable=0,pwrite=0;reg[7:0]paddr=0;reg[31:0]pwdata=0;reg[3:0]events=0;
 wire pready,pslverr;wire[31:0]prdata;rdl_regs #(.MUTATION(MUTATION),.WAIT_CYCLES(WAIT_CYCLES)) dut(.*);
 reg[7:0] cfg=18;reg[3:0] pending=0;integer fd,n,checks=0,waits;reg[31:0]v[0:4],expected;string vectors,wave;reg bad;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"operation=%0d",checks);end endtask
 task edge_tick;begin
 @(posedge clk);if(!rst_n)begin cfg=18;pending=0;end else begin
 if(psel&&penable&&pready&&!pslverr&&pwrite&&paddr==0)cfg=pwdata[7:0];
 pending=(pending & ~((psel&&penable&&pready&&!pslverr&&pwrite&&paddr==8)?pwdata[3:0]:4'b0))|events;
 end #1;@(negedge clk);
 end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");$dumpfile(wave);$dumpvars(0,rtl_tb);fd=$fopen(vectors,"r");repeat(2)edge_tick();rst_n=1;
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4]);if(n!=5)$fatal(1,"bad row");
 paddr=v[0];pwrite=v[1];pwdata=v[2];events=v[3];psel=1;penable=0;edge_tick();penable=1;events=v[4];waits=0;
 begin: access_loop
 for(integer i=0;i<WAIT_CYCLES+2;i=i+1)begin
 #1;bad=!(paddr==0 || paddr==4 || paddr==8) || (pwrite&&paddr==4);
 if(pready!==(waits==WAIT_CYCLES) || pslverr!==(pready&&bad))fail("RDL_RESPONSE");
 expected=paddr==0 ? {24'b0,cfg}:paddr==4 ? 32'h52444c31:paddr==8 ? {28'b0,pending}:0;
 if(!pwrite && prdata!==expected)fail("RDL_READ");
 if(pready)begin edge_tick();disable access_loop;end
 edge_tick();waits=waits+1;
 end fail("RDL_TIMEOUT");end
 psel=0;penable=0;events=0;edge_tick();checks=checks+1;
 end
 $display("COUNT operations=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
