`timescale 1ns/1ps
module owned_tb;
 parameter MUTATION=0,DEPTH=2,STALL_PERIOD=0;reg clk=0;always #5 clk=~clk;
 reg rst_n=0,host_valid=0;reg[2:0]host_op=0,host_slot=0;reg[12:0]host_src=0,host_dst=0;reg[5:0]host_words=0;wire host_ready,host_error,busy,irq;wire[7:0]retired;wire[2:0]head;wire[2*DEPTH-1:0]owners;wire[DEPTH-1:0]errors;
 wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;wire[12:0]araddr,awaddr;wire[7:0]arlen,awlen;wire[1:0]arid,awid,rid,rresp,bid,bresp;wire[31:0]rdata,wdata;wire[3:0]wstrb;wire ram_arready,ram_awready,ram_wready;reg gate=1,expected_irq=0,acked=0;reg[7:0]last_retired=0;
 owned_ring #(.DEPTH(DEPTH),.MUTATION(MUTATION))dut(.*);
 axi4_ram ram(.clk(clk),.rst_n(rst_n),.awvalid(awvalid&&gate),.awready(ram_awready),.awaddr(awaddr),.awlen(awlen),.awsize(3'd2),.awburst(2'd1),.awid(awid),.wvalid(wvalid&&gate),.wready(ram_wready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.bvalid(bvalid),.bready(bready),.bid(bid),.bresp(bresp),.arvalid(arvalid&&gate),.arready(ram_arready),.araddr(araddr),.arlen(arlen),.arsize(3'd2),.arburst(2'd1),.arid(arid),.rvalid(rvalid),.rready(rready),.rdata(rdata),.rid(rid),.rresp(rresp),.rlast(rlast));
 assign arready=ram_arready&&gate;assign awready=ram_awready&&gate;assign wready=ram_wready&&gate;
 integer fd,n,checks=0,cycles,turn,slot,write_slot,write_beat,write_turn;reg[31:0]v[0:5];reg[7:0]expected_memory[0:8191];reg[31:0]digest,expected_word;string vectors,wave;
 function automatic[7:0]initial_byte(input integer a);initial_byte=(a*13+7)^((a>>8)*8'h5b)^v[0];endfunction
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d cycle=%0d retired=%0d",checks,cycles,retired);end endtask
 task tick;begin
 #1;if(rst_n && head!==3'(retired%DEPTH))fail("OWN_ORDER");
 // IRQ rises on each return, ACK clears it (a same-edge return wins) and reset clears it.
 if(!rst_n)begin expected_irq=0;last_retired=0;acked=0;end
 else begin if(acked)expected_irq=0;if(retired!=last_retired)expected_irq=1;last_retired=retired;acked=host_valid && host_op==4;if(irq!==expected_irq)fail("OWN_IRQ");end
 if(awvalid && awready)begin
 write_slot=retired%DEPTH;write_turn=retired/DEPTH;write_beat=0;
 if(awaddr!=1024+32*write_slot || awid!=2 || awlen!=(write_slot+write_turn)%4)fail("OWN_BUS");end
 if(wvalid && wready)begin
 expected_word={initial_byte(v[5]+128*write_turn+16*write_slot+4*write_beat+3),initial_byte(v[5]+128*write_turn+16*write_slot+4*write_beat+2),initial_byte(v[5]+128*write_turn+16*write_slot+4*write_beat+1),initial_byte(v[5]+128*write_turn+16*write_slot+4*write_beat)};
 if(wdata!==expected_word || wstrb!=15)fail("OWN_DATA");write_beat=write_beat+1;end
 if(busy)begin $display("COVER engine/busy");if(owners[2*head+:2]!=2)fail("OWN_STATE");end
 @(posedge clk);#1;@(negedge clk);cycles=cycles+1;gate=STALL_PERIOD==0 || cycles%STALL_PERIOD!=0;if(cycles>8000)fail("OWN_TIMEOUT");
 end endtask
 task command(input integer op,input integer selected,input integer bad);
 begin host_op=op;host_slot=selected;host_valid=1;#1;
 if(!host_ready || host_error!==bad[0])fail("OWN_RESPONSE");if(bad)$display("COVER host/reject");
 tick();host_valid=0;
 if(!bad && op==1)begin if(owners[2*selected+:2]!=1)fail("OWN_STATE");$display("COVER host/publish");end
 if(!bad && op==2)begin if(owners[2*selected+:2]!=0)fail("OWN_STATE");$display("COVER host/reclaim");end
 end endtask
 task reset_all;begin rst_n=0;host_valid=0;tick();rst_n=1;for(integer a=0;a<8192;a=a+1)begin ram.memory[a]=initial_byte(a);expected_memory[a]=initial_byte(a);end tick();end endtask
 task publish(input integer t,input integer s);
 integer source,destination,length;begin
 source=v[5]+128*t+16*s;destination=1024+32*s;length=1+(s+t)%4;
 host_src=source+((v[2] && t==0 && s==DEPTH-1)?1:0);host_dst=destination;host_words=length;
 command(1,s,0);
 if(!(v[2] && t==0 && s==DEPTH-1))for(integer a=0;a<4*length;a=a+1)expected_memory[destination+a]=initial_byte(source+a);
 end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");$dumpfile(wave);$dumpvars(0,owned_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5]);if(n!=6)$fatal(1,"bad row");cycles=0;reset_all();
 if(v[3])begin host_src=256;host_dst=1024;host_words=4;command(1,0,0);command(3,0,0);while(!busy)tick();$display("COVER reset/pending");reset_all();$display("COVER reset/recovery");end
 command(2,0,1);command(7,0,1);command(1,DEPTH,1);
 for(turn=0;turn<v[1];turn=turn+1)begin
 if(turn==0)begin
 for(slot=0;slot<DEPTH;slot=slot+1)publish(turn,slot);
 command(1,0,1);command(2,0,1);command(3,0,0);
 end else begin
 command(2,0,0);publish(turn,0);while(!busy)tick();command(1,0,1);
 for(slot=1;slot<DEPTH;slot=slot+1)begin command(2,slot,0);publish(turn,slot);if(busy)$display("COVER host/dynamic");end
 end
 while(retired<(turn+1)*DEPTH)tick();
 if(retired!=(turn+1)*DEPTH || owners!={DEPTH{2'b11}})fail("OWN_STATE");
 if(errors!==(v[2] && turn==0 ? (1<<(DEPTH-1)):0))fail("OWN_STATUS");
 if(v[2] && turn==0)$display("COVER completion/error");if(!irq)fail("OWN_IRQ");$display("COVER completion/irq");
 command(4,0,0);if(irq)fail("OWN_IRQ");$display("COVER irq/ack");if(turn>0)$display("COVER ring/wrap");
 for(integer a=0;a<8192;a=a+1)if(ram.memory[a]!==expected_memory[a])fail("OWN_MEMORY");
 end
 digest=0;for(integer a=0;a<8192;a=a+1)digest=digest+(a+1)*ram.memory[a];if(digest!==v[4])fail("OWN_DIGEST");checks=checks+1;
 end $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end endmodule
