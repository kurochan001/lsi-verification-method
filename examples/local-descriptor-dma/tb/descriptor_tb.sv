`timescale 1ns/1ps
module descriptor_tb;
 parameter DEPTH=2,STALL_PERIOD=0,MUTATION=0;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,start=0,abort_req=0;reg[2:0]start_head=0,start_count=0;
 wire busy,irq,done,error,aborted;wire[2:0]completed;
 wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;
 wire[12:0]araddr,awaddr;wire[7:0]arlen,awlen;wire[1:0]arid,rid,rresp,awid,bid,bresp;wire[31:0]rdata,wdata;wire[3:0]wstrb;
 descriptor_dma #(.DEPTH(DEPTH),.MUTATION(MUTATION)) dut(.*);
 wire raw_arready,raw_awready,raw_wready;wire[1:0]raw_rresp,raw_bresp;
 integer tick_count=0,fetches=0,write_beat=0,active_slot=0,checks=0,fd,n,v[0:11];reg monitor=0,abort_fired=0;
 wire permit=STALL_PERIOD==0 || tick_count%(STALL_PERIOD+1)==STALL_PERIOD;
 wire abort_hold=!abort_fired && v[5]!=0 && ((v[5]==1 && arid==0 && fetches==v[4]) || (v[5]==2 && arid==1 && fetches-1==v[4]));
 assign arready=raw_arready && permit && !abort_hold;assign awready=raw_awready && permit;assign wready=raw_wready && permit;
 assign rresp=raw_rresp | ((v[3]==1 && rid==0 && fetches-1==v[4]) || (v[3]==3 && rid==1 && fetches-1==v[4]) ? 2'b10:0);
 assign bresp=raw_bresp | (v[3]==4 && fetches-1==v[4] ? 2'b10:0);
 axi4_ram memory(.clk(clk),.rst_n(rst_n),.awvalid(awvalid&&permit),.awaddr(awaddr),.awlen(awlen),.awsize(3'd2),.awburst(2'd1),.awid(awid),.awready(raw_awready),
 .wvalid(wvalid&&permit),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.wready(raw_wready),.bvalid(bvalid),.bready(bready),.bid(bid),.bresp(raw_bresp),
 .arvalid(arvalid&&permit&&!abort_hold),.araddr(araddr),.arlen(arlen),.arsize(3'd2),.arburst(2'd1),.arid(arid),.arready(raw_arready),.rvalid(rvalid),.rready(rready),.rdata(rdata),.rid(rid),.rresp(raw_rresp),.rlast(rlast));
 reg[7:0]expected[0:8191];reg[31:0]word;string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"operation=%0d",checks);end endtask
 function[7:0]initial_byte(input integer seed,input integer a);initial_byte=seed^(13*a)^(a>>5)^(a>>8);endfunction
 function integer source_address(input integer slot);source_address=64*slot;endfunction
 function integer destination_address(input integer slot);destination_address=1024+64*slot;endfunction
 task tick;begin @(posedge clk);#1;@(negedge clk);end endtask
 task reset_all;begin monitor=0;rst_n=0;start=0;abort_req=0;repeat(3)tick();rst_n=1;tick();end endtask
 always @(posedge clk)begin
 tick_count=tick_count+1;
 if(rst_n && monitor)begin
 if(arvalid && arready && arid==0)begin
 active_slot=(v[0]+fetches)%DEPTH;
 if(araddr!==6144+16*active_slot || arlen!==8'd3)fail("SG_FETCH");fetches=fetches+1;
 if(active_slot==0 && fetches>1)$display("COVER ring/wrap");
 end
 if(arvalid && arready && arid==1)begin
 if(araddr!==source_address(active_slot) || arlen!==active_slot)fail("SG_COPY_ADDRESS");
 end
 if(awvalid && awready)begin
 if(awaddr!==destination_address(active_slot) || awlen!==active_slot || awid!==2)fail("SG_COPY_ADDRESS");write_beat=0;
 end
 if(wvalid && wready)begin
 for(integer b=0;b<4;b=b+1)word[8*b+:8]=initial_byte(v[2],source_address(active_slot)+4*write_beat+b);
 if(wdata!==word || wstrb!==15 || wlast!==(write_beat==active_slot))fail("SG_DATA");write_beat=write_beat+1;
 end
 end end
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");$dumpfile(wave);$dumpvars(0,descriptor_tb);fd=$fopen(vectors,"r");@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]);if(n!=12)$fatal(1,"bad row");
 reset_all();abort_fired=0;
 if(v[6])begin start_head=0;start_count=1;start=1;tick();start=0;if(!busy)fail("SG_RESET");reset_all();$display("COVER reset/active");end
 for(integer a=0;a<8192;a=a+1)begin memory.memory[a]=initial_byte(v[2],a);expected[a]=initial_byte(v[2],a);end
 for(integer slot=0;slot<DEPTH;slot=slot+1)begin
 for(integer f=0;f<4;f=f+1)begin
 word=f==0 ? source_address(slot):f==1 ? destination_address(slot):f==2 ? slot+1:1;
 if(f==3 && v[3]==2 && slot==(v[0]+v[4])%DEPTH)word=0;
 for(integer b=0;b<4;b=b+1)begin memory.memory[6144+slot*16+f*4+b]=word[8*b+:8];expected[6144+slot*16+f*4+b]=word[8*b+:8];end
 end
 if(v[11]&(1<<slot))for(integer a=0;a<4*(slot+1);a=a+1)expected[destination_address(slot)+a]=initial_byte(v[2],source_address(slot)+a);
 end
 fetches=0;write_beat=0;monitor=1;start_head=v[0];start_count=v[1];start=1;tick();start=0;
 begin: completion
 for(integer guard=0;guard<3000;guard=guard+1)begin
 if(done)disable completion;
 if(v[5] && !abort_fired && arvalid && abort_hold)begin abort_req=1;tick();abort_req=0;abort_fired=1;end else tick();
 end fail("SG_TIMEOUT");end
 if({error,aborted,completed}!=={v[8][0],v[9][0],v[7][2:0]})fail("SG_STATUS");
 if(!irq)fail("SG_IRQ");if(fetches!=v[10])fail("SG_FETCH");
 for(integer a=0;a<8192;a=a+1)if(memory.memory[a]!==expected[a])fail("SG_MEMORY");
 monitor=0;
 if(v[1]==0)$display("COVER ring/empty");if(v[1]==DEPTH && !error && !aborted)$display("COVER ring/full");
 if(completed!=0)$display("COVER transfer/completed");if(v[3])$display("COVER fault/type%0d",v[3]);
 if(v[5])$display("COVER abort/type%0d",v[5]);if(v[0]>=DEPTH || v[1]>DEPTH)$display("COVER command/invalid");
 if(v[6] && !error && !aborted)$display("COVER reset/recovery");
 checks=checks+1;
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
