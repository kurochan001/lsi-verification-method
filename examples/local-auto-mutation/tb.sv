`timescale 1ns/1ps
module tb;
 reg clk=0,rst_n=0;reg [1:0]events=0,clear=0,mask=0;wire [1:0]pending;wire irq;wire [7:0]debug_hint;
 irq_regs dut(clk,rst_n,events,clear,mask,pending,irq,debug_hint);
 always #5 clk=!clk;
 integer fd,n,r,e,c,m,p,q,count=0;string vectors,wave;
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments missing");
  $dumpfile(wave);$dumpvars(0,tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h\n",r,e,c,m,p,q);
   if(n!=6)$fatal(1,"invalid vector");
   @(negedge clk);rst_n=1'(r);events=2'(e);clear=2'(c);mask=2'(m);
   @(posedge clk);#1;
   if(pending!==2'(p) || irq!==1'(q))begin $display("CHECK_FAIL IRQ_VALUE row=%0d",count);$fatal(1,"functional mismatch");end
   count++;
  end
  $fclose(fd);$display("MCY_COMPARE PASS checks=%0d",count);$finish;
 end
 initial begin #100000;$fatal(1,"watchdog");end
endmodule
