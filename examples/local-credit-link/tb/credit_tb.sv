`timescale 1ns/1ps
module credit_tb;
 parameter MUTATION=0,DEPTH=2;reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
reg in_valid=0;
reg in_channel=0;
reg [7:0] in_data=0;
reg [1:0] credit_return=0;
wire in_ready;
wire tx_valid;
wire tx_channel;
wire [7:0] tx_data;
wire [7:0] credits;
wire [7:0] queued;
wire bad_return;
 integer fd,n,checks=0;reg [63:0] v[0:11];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 credit_link #(.MUTATION(MUTATION),.DEPTH(DEPTH)) dut(.*);reg recovering=0,source_held=0;reg[8:0]old_source;
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,credit_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]);if(n!=12)$fatal(1,"bad vector");
 rst_n=v[0];
in_valid=v[1];
in_channel=v[2];
in_data=v[3];
credit_return=v[4];
 #1;
 if(in_ready!==v[5][0:0])fail("CREDIT_CONTROL");
if(tx_valid!==v[6][0:0])fail("CREDIT_CONTROL");
if(tx_channel!==v[7][0:0])fail("CREDIT_CONTROL");
if(tx_data!==v[8][7:0])fail("CREDIT_DATA");
if(credits!==v[9][7:0])fail("CREDIT_COUNT");
if(queued!==v[10][7:0])fail("CREDIT_COUNT");
if(bad_return!==v[11][0:0])fail("CREDIT_RETURN");

 if(!rst_n)source_held=0;
 else begin
 if(source_held && (!in_valid || {in_channel,in_data}!==old_source))fail("CREDIT_SOURCE");
 source_held=in_valid&&!in_ready;old_source={in_channel,in_data};end
 if(!rst_n)begin recovering=1;$display("COVER reset/clear");end
 if(tx_valid)begin
 if(tx_channel)$display("COVER channel/one");else $display("COVER channel/zero");
 if(recovering)begin $display("COVER reset/recovery");recovering=0;end
 if(credit_return[tx_channel])$display("COVER credit/simultaneous");
 if(in_valid && in_ready)$display("COVER queue/simultaneous");
 end
 if(rst_n && (credits[3:0]==0 || credits[7:4]==0))$display("COVER credit/exhausted");
 if(rst_n && credit_return!=0)$display("COVER credit/return");
 if(rst_n && in_valid && !in_ready)$display("COVER queue/blocked");
 if(bad_return)$display("COVER credit/bad-return");

 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
