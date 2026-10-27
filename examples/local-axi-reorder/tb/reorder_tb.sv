`timescale 1ns/1ps
module reorder_tb;
 parameter MUTATION=0,SLOTS=2;reg clk=0;always #5 clk=~clk;
 reg rst_n=0,release_enable=0,awvalid=0,wvalid=0,wlast=0,bready=0,arvalid=0,rready=0;
 reg[12:0]awaddr=0,araddr=0;reg[7:0]awlen=0,arlen=0;reg[2:0]awsize=2,arsize=2;reg[1:0]awburst=1,arburst=1,awid=0,arid=0;reg[31:0]wdata=0;reg[3:0]wstrb=0;
 wire awready,wready,bvalid,arready,rvalid,rlast;wire[1:0]bid,bresp,rid,rresp;wire[31:0]rdata;
 reorder #(.MUTATION(MUTATION),.SLOTS(SLOTS))dut(.*);
 integer fd,n,checks=0,cycles,position,transaction,beat,base,waits;reg[31:0]v[0:6];reg[7:0]expected_memory[0:8191];string vectors,wave;
 reg held_b=0,held_r=0;reg[3:0]saved_b;reg[36:0]saved_r;
 function automatic[31:0]pattern(input integer t,input integer b);pattern=v[3]^(32'h01020304*(t+1))^(32'h10203040*(b+1));endfunction
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d position=%0d beat=%0d",checks,position,beat);end endtask
 task tick;begin
 #1;
 if(held_b && (!bvalid || {bid,bresp}!==saved_b))fail("AXIO_HOLD");if(held_r && (!rvalid || {rid,rresp,rlast,rdata}!==saved_r))fail("AXIO_HOLD");
 if(bvalid && !bready)$display("COVER response/held");
 held_b=bvalid&&!bready;saved_b={bid,bresp};held_r=rvalid&&!rready;saved_r={rid,rresp,rlast,rdata};
 @(posedge clk);#1;@(negedge clk);cycles=cycles+1;if(cycles>4000)fail("AXIO_TIMEOUT");
 end endtask
 task reset_all;begin rst_n=0;release_enable=0;awvalid=0;wvalid=0;arvalid=0;bready=0;rready=0;held_b=0;held_r=0;tick();rst_n=1;for(integer a=0;a<8192;a=a+1)begin expected_memory[a]=(a*13+7)&255;dut.memory.memory[a]=expected_memory[a];end tick();end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");$dumpfile(wave);$dumpvars(0,reorder_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6]);if(n!=7)$fatal(1,"bad row");cycles=0;reset_all();
 if(v[5])begin arvalid=1;araddr=256;arlen=1;while(!arready)tick();tick();arvalid=0;repeat(5)tick();$display("COVER reset/pending");reset_all();$display("COVER reset/recovery");end
 for(transaction=0;transaction<SLOTS;transaction=transaction+1)begin
 awid=(v[0]>>(2*transaction))&3;awlen=(v[1]>>(2*transaction))&3;awaddr=256+32*transaction;awvalid=1;
 while(!awready)tick();tick();awvalid=0;
 for(beat=0;beat<=awlen;beat=beat+1)begin
 wdata=pattern(transaction,beat);wstrb=v[2];wlast=beat==awlen;wvalid=1;while(!wready)tick();
 for(integer lane=0;lane<4;lane=lane+1)if(wstrb[lane])expected_memory[awaddr+4*beat+lane]=wdata[8*lane+:8];tick();wvalid=0;
 end end
 repeat(20)tick();release_enable=1;
 for(position=0;position<SLOTS;position=position+1)begin
 transaction=(v[6]>>(2*position))&3;bready=0;
 while(!bvalid)tick();repeat(3)tick();
 if(bid!==((v[0]>>(2*transaction))&3))fail("AXIO_BID");if(bresp!=0)fail("AXIO_RESP");
 if(transaction!=position)$display("COVER response/b-reorder");bready=1;tick();bready=0;
 end release_enable=0;
 for(transaction=0;transaction<SLOTS;transaction=transaction+1)begin
 arid=(v[0]>>(2*transaction))&3;arlen=(v[1]>>(2*transaction))&3;araddr=256+32*transaction;arvalid=1;while(!arready)tick();tick();arvalid=0;
 end
 repeat(40)tick();release_enable=1;
 for(position=0;position<SLOTS;position=position+1)begin
 transaction=(v[6]>>(2*position))&3;
 for(beat=0;beat<=((v[1]>>(2*transaction))&3);beat=beat+1)begin
 rready=0;while(!rvalid)tick();if(v[4])repeat(3)tick();
 if(rid!==((v[0]>>(2*transaction))&3))fail("AXIO_RID");if(rresp!=0)fail("AXIO_RESP");
 base=256+32*transaction+4*beat;if(rdata!=={expected_memory[base+3],expected_memory[base+2],expected_memory[base+1],expected_memory[base]})fail("AXIO_DATA");
 if(rlast!==(beat==((v[1]>>(2*transaction))&3)))fail("AXIO_LAST");rready=1;tick();rready=0;
 end if(transaction!=position)$display("COVER response/r-reorder");
 end
 if(v[0]==0)$display("COVER order/same-id");
 for(integer i=0;i<SLOTS;i=i+1)for(integer j=i+1;j<SLOTS;j=j+1)if(((v[0]>>(2*i))&3)==((v[0]>>(2*j))&3))$display("COVER order/duplicate-id");
 if(v[1]!=0)$display("COVER burst/multiple");if(v[2]!=0 && v[2]!=15)$display("COVER write/partial");if(v[2]==0)$display("COVER write/zero");
 for(integer a=0;a<8192;a=a+1)if(dut.memory.memory[a]!==expected_memory[a])fail("AXIO_MEMORY");
 checks=checks+1;
 end $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end endmodule
