`timescale 1ns/1ps
module dma_tb;
 parameter MUTATION=0,STALL_PERIOD=0;
 reg clk=0;always #5 clk=~clk;reg rst_n=0,psel=0,penable=0,pwrite=0;
 reg [7:0] paddr=0;reg [31:0] pwdata=0;wire pready,pslverr,irq;wire [31:0] prdata;
 wire arvalid,arready,rvalid,rready,rlast,awvalid,awready,wvalid,wready,wlast,bvalid,bready;
 wire [12:0] araddr,awaddr;wire [7:0] arlen,awlen;wire [1:0] arid,rid,rresp,awid,bid,bresp;wire [31:0] rdata,wdata;wire [3:0] wstrb;
 apb_dma #(.MUTATION(MUTATION)) dut(.*);
 wire raw_arready,raw_awready,raw_wready;wire [1:0] raw_rresp,raw_bresp;
 reg hold_ar=0,hold_w=0;integer cycles=0,fault=0;
 wire permit=STALL_PERIOD==0 || cycles%(STALL_PERIOD+1)==STALL_PERIOD;
 wire arpermit=permit&&!hold_ar,wpermit=permit&&!hold_w;
 assign arready=raw_arready&&arpermit;assign awready=raw_awready&&permit;assign wready=raw_wready&&wpermit;
 assign rresp=raw_rresp | (fault==1 ? 2'b10:0);assign bresp=raw_bresp | (fault==2 ? 2'b10:0);
 axi4_ram memory(.clk(clk),.rst_n(rst_n),.awvalid(awvalid&&permit),.awaddr(awaddr),.awlen(awlen),.awsize(3'd2),.awburst(2'd1),.awid(awid),.awready(raw_awready),
  .wvalid(wvalid&&wpermit),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.wready(raw_wready),.bvalid(bvalid),.bready(bready),.bid(bid),.bresp(raw_bresp),
  .arvalid(arvalid&&arpermit),.araddr(araddr),.arlen(arlen),.arsize(3'd2),.arburst(2'd1),.arid(arid),.arready(raw_arready),
  .rvalid(rvalid),.rready(rready),.rdata(rdata),.rid(rid),.rresp(raw_rresp),.rlast(rlast));
 integer fd,n,v[0:13],checks=0,starts=0,read_bursts=0,write_bursts=0,read_beats=0,write_beats=0,completions=0;
 integer local_reads=0,local_writes=0,read_addresses=0,write_addresses=0,current_wlen=0,current_wbeat=0;
 reg monitor=0,arheld=0,awheld=0,wheld=0;reg [22:0] oldar,oldaw;reg [36:0] oldw;
 reg [31:0] value,expected_word;reg [7:0] expected_byte;string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"batch=%0d cycle=%0d",checks,cycles);end endtask
 function [7:0] initial_byte(input integer seed,input integer address);initial_byte=seed ^ (13*address) ^ (address>>5) ^ (address>>8);endfunction
 always @(posedge clk)begin
  cycles=cycles+1;
  if(rst_n && psel && penable && pwrite && pready && !pslverr && paddr==12 && pwdata[0])starts=starts+1;
  if(monitor && rst_n)begin
   if(arheld && (!arvalid || {araddr,arlen,arid}!==oldar))fail("DMA_PROTOCOL");
   if(awheld && (!awvalid || {awaddr,awlen,awid}!==oldaw))fail("DMA_PROTOCOL");
   if(wheld && (!wvalid || {wdata,wstrb,wlast}!==oldw))fail("DMA_PROTOCOL");
   arheld=arvalid&&!arready;awheld=awvalid&&!awready;wheld=wvalid&&!wready;
   oldar={araddr,arlen,arid};oldaw={awaddr,awlen,awid};oldw={wdata,wstrb,wlast};
   if(arvalid && arready)begin
    if(araddr[11:0]+4*(arlen+1)>4096 || arlen>3)fail("DMA_BOUNDARY");
    if(araddr!==v[0]+4*read_addresses || arid!=1)fail("DMA_ADDRESS");
    read_addresses=read_addresses+arlen+1;read_bursts=read_bursts+1;
    if(araddr==4096 || araddr+4*(arlen+1)==4096)$display("COVER boundary/source-split");
   end
   if(awvalid && awready)begin
    if(awaddr[11:0]+4*(awlen+1)>4096 || awlen>3)fail("DMA_BOUNDARY");
    if(awaddr!==v[1]+4*write_addresses || awid!=2)fail("DMA_ADDRESS");
    write_addresses=write_addresses+awlen+1;current_wlen=awlen;current_wbeat=0;write_bursts=write_bursts+1;
    if(awaddr==4096 || awaddr+4*(awlen+1)==4096)$display("COVER boundary/destination-split");
   end
   if(rvalid && rready)begin local_reads=local_reads+1;read_beats=read_beats+1;end
   if(wvalid && wready)begin
    for(integer lane=0;lane<4;lane=lane+1)expected_word[8*lane+:8]=initial_byte(v[3],v[0]+4*local_writes+lane);
    if(wdata!==expected_word || wstrb!==4'hf)fail("DMA_DATA");
    if(wlast!==(current_wbeat==current_wlen))fail("DMA_PROTOCOL");
    current_wbeat=current_wbeat+1;local_writes=local_writes+1;write_beats=write_beats+1;
   end
  end
 end
 task tick;begin @(posedge clk);#1;@(negedge clk);end endtask
 task apb(input integer address,input integer write,input integer data,input integer error,output reg [31:0] result);
  begin
   psel=1;penable=0;pwrite=write;paddr=address;pwdata=data;tick();penable=1;#1;
   if(!pready || pslverr!==error[0])fail("DMA_APB");result=prdata;
   tick();psel=0;penable=0;
  end
 endtask
 task program_dma(input integer source,input integer destination,input integer words,input integer mask);
  begin apb(0,1,source,0,value);apb(4,1,destination,0,value);apb(8,1,words,0,value);apb(20,1,!mask,0,value);apb(12,1,1,0,value);end
 endtask
 task reset_bus;
  begin monitor=0;psel=0;penable=0;rst_n=0;repeat(3)tick();rst_n=1;tick();arheld=0;awheld=0;wheld=0;end
 endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,dma_tb);@(negedge clk);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13]);if(n!=14)$fatal(1,"bad row");
   reset_bus();hold_ar=0;hold_w=0;fault=v[4];
   if(v[6])begin
    hold_ar=1;program_dma(0,256,4,0);
    if(!arvalid)fail("DMA_RESET");reset_bus();hold_ar=0;
    if(arvalid || awvalid || wvalid || irq)fail("DMA_RESET");
   end
   for(integer address=0;address<8192;address=address+1)memory.memory[address]=initial_byte(v[3],address);
   local_reads=0;local_writes=0;read_addresses=0;write_addresses=0;current_wbeat=0;monitor=1;
   hold_ar=v[5]==1;hold_w=v[5]==2;program_dma(v[0],v[1],v[2],v[7]);
   if(v[5])begin
    begin: abort_wait for(integer guard=0;guard<500;guard=guard+1)begin
     if((v[5]==1 && arvalid) || (v[5]==2 && wvalid))disable abort_wait;tick();
    end fail("DMA_TIMEOUT");end
    apb(0,1,0,1,value);apb(12,1,1,1,value); // Busy programming/start must be rejected.
    apb(12,1,2,0,value);hold_ar=0;hold_w=0;$display("COVER abort/phase%0d",v[5]);
   end
   begin: completion_wait for(integer guard=0;guard<2000;guard=guard+1)begin
    apb(16,0,0,0,value);if(value[1])disable completion_wait;
   end fail("DMA_TIMEOUT");end
   if(value[4]!==1'b1)fail("DMA_IRQ");
   if(value[3:0]!=={v[9][0],v[8][0],2'b10})fail("DMA_STATUS");
   if(irq!==!v[7][0])fail("DMA_IRQ");
   if(v[7])begin apb(20,1,1,0,value);#1;if(!irq)fail("DMA_IRQ");$display("COVER irq/mask-unmask");end
   apb(12,1,4,0,value);#1;if(irq)fail("DMA_IRQ");$display("COVER irq/clear");
   if(local_reads!=v[11] || local_writes!=v[10] || read_addresses!=v[11] || write_addresses!=v[10])fail("DMA_COUNT");
   for(integer address=0;address<8192;address=address+1)begin
    expected_byte=initial_byte(v[3],address);
    if(address>=v[1] && address<v[1]+4*v[10])expected_byte=initial_byte(v[3],v[0]+address-v[1]);
    if(memory.memory[address]!==expected_byte)fail("DMA_MEMORY");
   end
   monitor=0;completions=completions+1;
   if(v[6] && !v[8] && !v[9] && v[2]>0)$display("COVER reset/active-and-recovery");
   if(v[2]==0)$display("COVER transfer/zero");else if(!v[8] && !v[9])$display("COVER transfer/copy");
   if(v[4])$display("COVER response/fault%0d",v[4]);
   if(v[8] && !v[4])$display("COVER command/invalid");
   checks=checks+1;
  end
  $display("COUNT starts=%0d",starts);$display("COUNT read_bursts=%0d",read_bursts);$display("COUNT write_bursts=%0d",write_bursts);
  $display("COUNT read_beats=%0d",read_beats);$display("COUNT write_beats=%0d",write_beats);$display("COUNT completions=%0d",completions);
  $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
