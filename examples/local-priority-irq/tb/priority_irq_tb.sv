`timescale 1ns/1ps
module priority_irq_tb;
 parameter MUTATION=0,LEVEL=1,WAIT_CYCLES=1;reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
reg psel=0;
reg penable=0;
reg pwrite=0;
reg [7:0] paddr=0;
reg [31:0] pwdata=0;
reg [3:0] sources=0;
wire pready;
wire pslverr;
wire irq;
wire [31:0] prdata;
wire [3:0] pending;
wire [3:0] in_service;
 integer fd,n,checks=0;reg [63:0] v[0:12];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 priority_irq #(.MUTATION(MUTATION),.LEVEL(LEVEL),.WAIT_CYCLES(WAIT_CYCLES)) dut(.*);integer equals;
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,priority_irq_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12]);if(n!=13)$fatal(1,"bad vector");
 rst_n=v[0];
psel=v[1];
penable=v[2];
pwrite=v[3];
paddr=v[4];
pwdata=v[5];
sources=v[6];
 #1;
 if(pready!==v[7][0:0])fail("PRIO_BUS");
if(pslverr!==v[8][0:0])fail("PRIO_BUS");
if(irq!==v[9][0:0])fail("PRIO_IRQ");
if(prdata!==v[10][31:0])fail("PRIO_READ");
if(pending!==v[11][3:0])fail("PRIO_PENDING");
if(in_service!==v[12][3:0])fail("PRIO_SERVICE");

 if(!rst_n && pending==0 && in_service==0)$display("COVER reset/clear");
 if(rst_n && (pending&~dut.enables)!=0)$display("COVER pending/masked");
 if(rst_n && (sources&in_service)!=0)$display("COVER service/blocked-event");
 if(rst_n && dut.winner!=0 && dut.best==dut.threshold && !irq)$display("COVER policy/threshold");
 if(pready)begin
 if(pslverr)begin $display("COVER bus/error");if(paddr==16 && pwrite)$display("COVER service/invalid");end
 else if(paddr==16)begin
 if(pwrite)$display("COVER service/complete");
 else if(prdata==0)$display("COVER select/empty");
 else begin
 $display("COVER select/claim");if(!irq)$display("COVER policy/claim-below-threshold");
 equals=0;for(integer i=0;i<4;i=i+1)if(pending[i] && dut.enables[i] && dut.priorities[i]==dut.best)equals=equals+1;
 if(equals>1)$display("COVER select/tie");else $display("COVER select/priority");
 end end end

 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
