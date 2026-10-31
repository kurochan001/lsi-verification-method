`timescale 1ns/1ps
module sha256_tb;
 parameter ROUNDS=1,MUTATION=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,cmd_valid=0,byte_valid=0,digest_ready=0;
 reg [6:0] length=0;reg [7:0] byte_data=0;
 wire cmd_ready,byte_ready,digest_valid,error;wire [255:0] digest;
 sha256_engine #(.ROUNDS(ROUNDS),.MUTATION(MUTATION)) dut(.*);
 integer fd,n,checks=0,accepted_bytes=0;reg [255:0] v[0:10];string vectors,wave;
 reg pending=0;reg [6:0] saved_length=0;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,sha256_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10]);if(n!=11)$fatal(1,"bad row");
   rst_n=v[0][0];cmd_valid=v[1][0];length=v[2][6:0];byte_valid=v[3][0];byte_data=v[4][7:0];digest_ready=v[5][0];#1;
   if(cmd_ready!==v[6][0] || byte_ready!==v[7][0] || (rst_n && digest_valid!==v[8][0]))fail("SHA_FLOW");
   if(rst_n && digest_valid && (error!==v[9][0] || digest!==v[10]))fail("SHA_DIGEST");
   if(!rst_n)begin if(pending)$display("COVER reset/pending");pending=0;end
   else begin
    if(cmd_valid && cmd_ready)begin
     pending=1;saved_length=length;accepted_bytes=0;
     if(length==0)$display("COVER length/empty");
     if(length==55)$display("COVER length/55");if(length==56)$display("COVER length/56");
     if(length==64)$display("COVER length/64");if(length==119)$display("COVER length/maximum");
     if(length>119)$display("COVER length/rejected");
    end
    if(cmd_valid && !cmd_ready)$display("COVER command/busy");
    if(byte_ready && !byte_valid)$display("COVER input/gap");
    if(byte_ready && byte_valid)begin accepted_bytes=accepted_bytes+1;$display("COVER input/accepted");end
    if(dut.state==4 && dut.second)$display("COVER compression/second-block");
    if(digest_valid)begin
     if(!error && accepted_bytes!=saved_length)fail("SHA_LENGTH");
     if(!error && saved_length<=55)$display("COVER result/one-block");
     if(!error && saved_length>55)$display("COVER result/two-block");
     if(!digest_ready)$display("COVER result/hold");
     if(digest_ready)begin pending=0;$display("COVER result/accepted");end
    end
   end
   @(posedge clk);#1;checks=checks+1;@(negedge clk);
  end
  if(pending)fail("SHA_UNDRAINED");
  $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
