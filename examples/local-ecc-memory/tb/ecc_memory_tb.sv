`timescale 1ns/1ps
module ecc_memory_tb;
 parameter MUTATION=0,DEPTH=4;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
reg wr_en=0;
reg rd_en=0;
reg scrub_en=0;
reg inject_en=0;
reg [2:0] addr=0;
reg [2:0] inject_addr=0;
reg [7:0] wr_data=0;
reg [12:0] inject_mask=0;
wire [7:0] rd_data;
wire corrected;
wire uncorrectable;
wire [2:0] scrub_addr;
wire scrub_corrected;
wire scrub_uncorrectable;
 integer fd,n,checks=0;reg [63:0] v[0:14];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
 ecc_memory #(.MUTATION(MUTATION),.DEPTH(DEPTH)) dut(.clk(clk),.rst_n(rst_n),.wr_en(wr_en),.rd_en(rd_en),.scrub_en(scrub_en),.inject_en(inject_en),.addr(addr[$clog2(DEPTH)-1:0]),.inject_addr(inject_addr[$clog2(DEPTH)-1:0]),.wr_data(wr_data),.inject_mask(inject_mask),.rd_data(rd_data),.corrected(corrected),.uncorrectable(uncorrectable),.scrub_addr(),.scrub_corrected(scrub_corrected),.scrub_uncorrectable(scrub_uncorrectable));
assign scrub_addr=dut.scrub_addr;reg after_reset=0;integer bits;
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,ecc_memory_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14]);if(n!=15)$fatal(1,"bad row");
 rst_n=v[0];
wr_en=v[1];
rd_en=v[2];
scrub_en=v[3];
inject_en=v[4];
addr=v[5];
inject_addr=v[6];
wr_data=v[7];
inject_mask=v[8];
 #1;
 if(rd_data!==v[9][7:0])fail("ECC_MEMORY_DATA");
if(corrected!==v[10][0:0])fail("ECC_MEMORY_FLAGS");
if(uncorrectable!==v[11][0:0])fail("ECC_MEMORY_FLAGS");
if(scrub_addr!==v[12][2:0])fail("ECC_MEMORY_CONTROL");
if(scrub_corrected!==v[13][0:0])fail("ECC_MEMORY_FLAGS");
if(scrub_uncorrectable!==v[14][0:0])fail("ECC_MEMORY_FLAGS");

 if(!rst_n)after_reset=1;
 if(rst_n && rd_en)begin
 if(uncorrectable)$display("COVER read/uncorrectable");else if(corrected)$display("COVER read/corrected");else $display("COVER read/clean");
 if(after_reset && rd_data==0 && !corrected && !uncorrectable)begin $display("COVER reset/read-zero");after_reset=0;end
 end
 if(scrub_corrected)$display("COVER scrub/corrected");if(scrub_uncorrectable)$display("COVER scrub/uncorrectable");
 if(rst_n && scrub_en && scrub_addr==DEPTH-1)$display("COVER scrub/wrap");
 if(rst_n && scrub_en && wr_en && addr==scrub_addr && dut.scrub_c)$display("COVER race/write-wins");
 if(rst_n && scrub_en && rd_en && addr==scrub_addr && corrected)$display("COVER race/read-and-scrub");
 if(rst_n && inject_en)begin bits=$countones(inject_mask);if(bits==1)$display("COVER fault/single");if(bits==2)$display("COVER fault/double");end

 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
 endmodule
