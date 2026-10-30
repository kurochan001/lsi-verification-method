`timescale 1ns/1ps
module access_tb;
 parameter MUTATION=0,WAIT_CYCLES=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
reg psel=0;
reg penable=0;
reg pwrite=0;
reg [7:0] paddr=0;
reg [31:0] pwdata=0;
reg [2:0] pprot=0;
wire pready;
wire pslverr;
wire [31:0] prdata;
wire [31:0] public_value;
wire [31:0] secret_value;
wire locked;
 integer fd,n,checks=0;reg [63:0] v[0:12];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
 protected_regs #(.MUTATION(MUTATION),.WAIT_CYCLES(WAIT_CYCLES)) dut(.*);reg was_reset=0,lock_seen=0;
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,access_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12]);if(n!=13)$fatal(1,"bad row");
 rst_n=v[0];
psel=v[1];
penable=v[2];
pwrite=v[3];
paddr=v[4];
pwdata=v[5];
pprot=v[6];
 #1;
 if(pready!==v[7][0:0])fail("ACCESS_RESPONSE");
if(pslverr!==v[8][0:0])fail("ACCESS_RESPONSE");
if(!pwrite && prdata!==v[9][31:0])fail("ACCESS_READ");
if(public_value!==v[10][31:0])fail("ACCESS_STATE");
if(secret_value!==v[11][31:0])fail("ACCESS_STATE");
if(locked!==v[12][0:0])fail("ACCESS_STATE");

 if(!rst_n)begin was_reset=lock_seen;lock_seen=0;end else if(locked)lock_seen=1;
 if(rst_n && psel && !penable)$display("COVER apb/setup");
 if(pready)begin
 $display("COVER apb/completed");
 if(!pslverr)begin
 if(paddr==0)$display("COVER access/public");
 if(paddr==16)begin $display("COVER access/config");if(pwrite && was_reset)begin $display("COVER reset/reconfigure");was_reset=0;end end
 if(paddr==20 && pwrite && pwdata[0])$display("COVER lock/set");
 if(paddr==20 && pwrite && !pwdata[0] && locked)$display("COVER lock/cannot-unlock");
 end else begin
 if(pwrite)$display("COVER deny/write");else $display("COVER deny/read");
 if(paddr!=0 && paddr!=16 && paddr!=20)$display("COVER deny/unmapped");
 else if(paddr==16 || paddr==20)begin
 if(!pprot[0])$display("COVER deny/unprivileged");if(pprot[1])$display("COVER deny/nonsecure");if(pprot[2])$display("COVER deny/instruction");
 if(paddr==16 && pwrite && locked && pprot==1)$display("COVER lock/deny-write");end
 end end

 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
 endmodule
