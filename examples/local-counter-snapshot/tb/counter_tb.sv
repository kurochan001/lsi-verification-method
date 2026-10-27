`timescale 1ns/1ps
module counter_tb;
 parameter MUTATION=0,WAIT_CYCLES=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,psel=0,penable=0,pwrite=0;reg[7:0]paddr=0;reg[31:0]pwdata=0;wire pready,pslverr,irq,pending,snapshot_valid;wire[31:0]prdata;wire[63:0]count;reg[63:0]old_count=0;reg old_pending=0,recovering=0;
 counter #(.MUTATION(MUTATION),.WAIT_CYCLES(WAIT_CYCLES)) dut(.*);
 integer fd,n,checks=0;reg[63:0]v[0:12];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");
 $dumpfile(wave);$dumpvars(0,counter_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12]);if(n!=13)$fatal(1,"bad row");
 rst_n=v[0];
 psel=v[1];
 penable=v[2];
 pwrite=v[3];
 paddr=v[4];
 pwdata=v[5];
 #1;
 if(pready!==v[6][0] || pslverr!==v[7][0])fail("COUNT_BUS");
 if(prdata!==v[8][31:0])fail("COUNT_READ");
 if(count!==v[9])fail("COUNT_STATE");
 if(pending!==v[10][0] || irq!==v[11][0])fail("COUNT_IRQ");
 if(snapshot_valid!==v[12][0])fail("COUNT_SNAPSHOT");
 if(!rst_n)recovering=1;
 if(rst_n && count[63:32]!=old_count[63:32])$display("COVER count/low-roll");if(rst_n && old_count>64'hfffffffffffffff0 && count<16)$display("COVER count/full-wrap");
 if(rst_n && pending && !old_pending)$display("COVER irq/set");if(rst_n && !pending && old_pending)$display("COVER irq/clear");
 if(snapshot_valid && count[63:32]!=dut.snapshot_high)$display("COVER snapshot/held");
 if(pready)begin
 if(pslverr)$display("COVER bus/error");
 if(!pslverr && !pwrite && paddr==4 && snapshot_valid)$display("COVER snapshot/read");
 if(!pslverr && pwrite && paddr==8)$display("COVER load/staged");
 if(!pslverr && pwrite && paddr==28 && pwdata[0] && dut.match)$display("COVER irq/collision");
 if(recovering)begin $display("COVER reset/recovery");recovering=0;end
 end old_count=count;old_pending=pending;
 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
