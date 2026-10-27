`timescale 1ns/1ps
module stream_dma_tb;
 parameter MUTATION=0,FIFO_DEPTH=2,STALL_PERIOD=0;reg clk=0;always #5 clk=~clk;
 reg rst_n=0,start=0,direction=0;reg[12:0]address=0;reg[5:0]byte_count=0;wire busy,done,error,irq;
 wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;
 wire[12:0]araddr,awaddr;wire[7:0]arlen,awlen;wire[1:0]arid,awid,rid,rresp,bid,bresp;wire[31:0]rdata,wdata;wire[3:0]wstrb;
 wire m_valid,m_ready,m_last;wire[31:0]m_data;wire[3:0]m_keep;reg s_valid=0,s_last=0;wire s_ready;reg[31:0]s_data=0;reg[3:0]s_keep=0;
 wire f_valid,f_last;wire[31:0]f_data;wire[3:0]f_keep;reg f_ready=0;
 wire ram_arready,ram_awready,ram_wready;wire[1:0]ram_rresp,ram_bresp;reg gate=1;
 integer fd,n,checks=0,cycles,sent,seen,reads,writes,read_responses,write_responses,mode,position,base;reg[31:0]v[0:7];string vectors,wave;
 reg hold_m=0;reg[36:0]saved_m;reg hold_s=0;reg[36:0]saved_s;
 stream_dma #(.MUTATION(MUTATION))dut(.*);
 axis_packet_fifo #(.DEPTH(FIFO_DEPTH))fifo(.clk(clk),.rst_n(rst_n),.s_valid(m_valid),.s_ready(m_ready),.s_data(m_data),.s_keep(m_keep),.s_last(m_last),.m_valid(f_valid),.m_ready(f_ready),.m_data(f_data),.m_keep(f_keep),.m_last(f_last));
 assign arready=ram_arready && gate;assign awready=ram_awready && gate;assign wready=ram_wready && gate;
 assign rresp=(mode==1 && read_responses==position)?2:ram_rresp;assign bresp=(mode==2 && write_responses==position)?2:ram_bresp;
 axi4_ram ram(.clk(clk),.rst_n(rst_n),.awvalid(awvalid&&gate),.awready(ram_awready),.awaddr(awaddr),.awlen(awlen),.awsize(3'd2),.awburst(2'd1),.awid(awid),.wvalid(wvalid&&gate),.wready(ram_wready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.bvalid(bvalid),.bready(bready),.bid(bid),.bresp(ram_bresp),.arvalid(arvalid&&gate),.arready(ram_arready),.araddr(araddr),.arlen(arlen),.arsize(3'd2),.arburst(2'd1),.arid(arid),.rvalid(rvalid),.rready(rready),.rdata(rdata),.rid(rid),.rresp(ram_rresp),.rlast(rlast));
 function automatic[7:0]initial_byte(input integer a);initial_byte=(a*13+7)^v[3];endfunction
 function automatic[31:0]payload(input integer b);payload=v[3]^(32'h01020304*b)^32'ha1b2c3d4;endfunction
 function automatic[3:0]mask(input integer b);integer left;begin left=v[2]-4*b;mask=left>=4?15:(1<<left)-1;end endfunction
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d cycle=%0d sent=%0d seen=%0d",checks,cycles,sent,seen);end endtask
 task tick;reg[31:0]expected;reg accepted_r,accepted_b;begin
 #1;
 if(hold_m && (!m_valid || {m_last,m_keep,m_data}!==saved_m))fail("STREAM_HOLD");hold_m=m_valid&&!m_ready;saved_m={m_last,m_keep,m_data};
 if(hold_s && (!s_valid || {s_last,s_keep,s_data}!==saved_s))fail("STREAM_SOURCE");hold_s=s_valid&&!s_ready;saved_s={s_last,s_keep,s_data};
 if(arvalid && arready)begin if(araddr!=v[1]+4*reads || arlen!=0 || arid!=1)fail("STREAM_AR");reads=reads+1;end
 if(awvalid && awready)begin if(awaddr!=v[1]+4*writes || awlen!=0 || awid!=2)fail("STREAM_AW");end
 if(wvalid && wready)begin if(wdata!==payload(writes) || wstrb!==mask(writes) || !wlast)fail("STREAM_MEMORY");writes=writes+1;end
 accepted_r=rvalid && rready;accepted_b=bvalid && bready;
 if(s_valid && s_ready)sent=sent+1;
 if(f_valid && !f_ready)$display("COVER stream/held");
 if(f_valid && f_ready)begin
 if(seen>=(v[7]+3)/4)fail("STREAM_COUNT");if(f_keep!==mask(seen))fail("STREAM_KEEP");if(f_last!==(4*(seen+1)>=v[2]))fail("STREAM_LAST");
 base=v[1]+4*seen;expected={initial_byte(base+3),initial_byte(base+2),initial_byte(base+1),initial_byte(base)};
 for(integer lane=0;lane<4;lane=lane+1)if(f_keep[lane] && f_data[8*lane+:8]!==expected[8*lane+:8])fail("STREAM_DATA");seen=seen+1;
 end
 @(posedge clk);#1;if(accepted_r)read_responses=read_responses+1;if(accepted_b)write_responses=write_responses+1;@(negedge clk);cycles=cycles+1;if(cycles>2000)fail("STREAM_TIMEOUT");
 end endtask
 task reset_all;begin rst_n=0;start=0;s_valid=0;f_ready=0;hold_m=0;hold_s=0;gate=1;tick();rst_n=1;for(integer a=0;a<8192;a=a+1)ram.memory[a]=initial_byte(a);reads=0;writes=0;read_responses=0;write_responses=0;seen=0;sent=0;tick();end endtask
 task begin_transfer;begin start=1;tick();start=0;end endtask
 task drive_source;begin
 s_valid=direction && sent<(v[2]+3)/4;s_data=payload(sent);s_keep=mask(sent);s_last=4*(sent+1)>=v[2];
 if(mode==3 && sent==position)s_last=!s_last;if(mode==4 && sent==position)s_keep=s_keep^1;
 end endtask
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"args required");$dumpfile(wave);$dumpvars(0,stream_dma_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7]);if(n!=8)$fatal(1,"bad row");cycles=0;mode=v[4];position=v[5];direction=v[0];address=v[1];byte_count=v[2];reset_all();
 if(mode==5)begin begin_transfer();repeat(2)tick();if(!busy)fail("STREAM_RESET");$display("COVER reset/pending");reset_all();mode=0;$display("COVER reset/recovery");end
 begin_transfer();
 while(!done || (!direction && seen<(v[7]+3)/4))begin
 gate=STALL_PERIOD==0 || cycles%STALL_PERIOD!=0;f_ready=cycles>40 && (STALL_PERIOD==0 || cycles%STALL_PERIOD!=1);drive_source();tick();end
 // After done, only outstanding source offers remain; next reset cancels them.
 f_ready=1;repeat(3)tick();
 if(error!==v[6][0] || !irq || busy)fail("STREAM_STATUS");
 if(!direction && seen!=(v[7]+3)/4)fail("STREAM_COUNT");if(direction && writes!=(v[7]+3)/4)fail("STREAM_COUNT");
 for(integer a=0;a<8192;a=a+1)begin
 if(direction && a>=v[1] && a<v[1]+v[7])begin base=(a-v[1])/4;if(ram.memory[a]!==((payload(base)>>(8*((a-v[1])%4)))&255))fail("STREAM_MEMORY");end
 else if(ram.memory[a]!==initial_byte(a))fail("STREAM_MEMORY");
 end
 if(direction)$display("COVER direction/s2mm");else $display("COVER direction/mm2s");if(v[2]==0)$display("COVER length/zero");if(v[2]%4!=0)$display("COVER length/partial");
 case(v[4])1:$display("COVER fault/read");2:$display("COVER fault/write");3:$display("COVER fault/last");4:$display("COVER fault/keep");default:;endcase
 if(v[1]%4!=0 || v[2]>32)$display("COVER request/error");checks=checks+1;
 end $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end endmodule
