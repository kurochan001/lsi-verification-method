`timescale 1ns/1ps
module recovery_tb;
 parameter MUTATION=0,TIMEOUT=4,TAG_BITS=4;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
 reg u_valid=0;
 reg [7:0] u_data=0;
 reg u_ready_response=0;
 reg d_ready=0;
 reg d_response=0;
 reg [15:0] response_tag=0;
 reg [7:0] response_data=0;
 wire u_ready;
 wire u_response;
 wire u_error;
 wire [7:0] u_result;
 wire d_valid;
 wire [7:0] d_data;
 wire [15:0] d_tag;
 wire response_ready;
 wire late_dropped;
 timeout_guard #(.MUTATION(MUTATION),.TIMEOUT(TIMEOUT),.TAG_BITS(TAG_BITS)) dut(.*);integer requests=0,responses=0,timeouts=0,dropped=0;reg flushed=0;
 integer fd,n,v[0:16],checks=0;string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,recovery_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],v[16]);
 if(n!=17)$fatal(1,"bad row");
 rst_n=v[0];
 u_valid=v[1];
 u_data=v[2];
 u_ready_response=v[3];
 d_ready=v[4];
 d_response=v[5];
 response_tag=v[6];
 response_data=v[7];
 #1;
 if(u_ready!==v[8][0:0] || u_response!==v[9][0:0] || d_valid!==v[12][0:0] || response_ready!==v[15][0:0] || late_dropped!==v[16][0:0])fail("RECOVERY_CONTROL");
 if(u_response && (u_error!==v[10][0] || u_result!==v[11][7:0]))fail("RECOVERY_CONTROL");
 if(d_valid && (d_tag!==v[14][15:0] || d_data!==v[13][7:0]))fail("RECOVERY_TAG");
 if(rst_n && u_valid && u_ready)begin requests=requests+1;$display("COVER request/accepted");end
 if(rst_n && (&dut.serial) && !u_ready)$display("COVER request/tag-exhausted");
 if(d_valid && !d_ready)$display("COVER request/held");
 if(u_response && !u_ready_response)$display("COVER response/held");
 if(u_response && u_ready_response)begin
  responses=responses+1;if(u_error)begin timeouts=timeouts+1;$display("COVER response/timeout");end
  else begin $display("COVER response/okay");if(timeouts>0)$display("COVER recovery/okay-after-timeout");end
 end
 if(late_dropped)begin dropped=dropped+1;$display("COVER response/late-dropped");end
 if(rst_n && d_response && d_tag==response_tag && dut.age==TIMEOUT-1 && dut.state==2)$display("COVER response/deadline-wins");
 if(!rst_n && checks>0)flushed=1;
 if(rst_n && u_response && u_ready_response && !u_error && flushed)begin $display("COVER reset/recovery");flushed=0;end
 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT requests=%0d",requests);$display("COUNT responses=%0d",responses);$display("COUNT timeouts=%0d",timeouts);$display("COUNT dropped=%0d",dropped);
 $display("RESULT PASS checks=%0d",checks);$finish;end
endmodule
