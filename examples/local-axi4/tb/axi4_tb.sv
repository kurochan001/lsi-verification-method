`timescale 1ns/1ps
module axi4_tb;
 parameter MUTATION=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,awvalid=0,wvalid=0,wlast=0,bready=0,arvalid=0,rready=0;
 reg [12:0] awaddr=0,araddr=0;
 reg [7:0] awlen=0,arlen=0;
 reg [2:0] awsize=2,arsize=2;
 reg [1:0] awburst=1,arburst=1,awid=0,arid=0;
 reg [31:0] wdata=0;reg [3:0] wstrb=15;
 wire awready,wready,bvalid,arready,rvalid,rlast;
 wire [1:0] bid,bresp,rid,rresp;wire [31:0] rdata;
 axi4_ram #(.MUTATION(MUTATION)) dut(.*);
 integer v[0:21],fd,n,checks=0,cycles=0,q,k,beat;
 integer writes=0,reads=0,write_beats=0,read_beats=0,errors=0;
 integer wc=0,rc=0;reg count_enable=0;
 reg bs=0,rs=0;reg [3:0] oldb;reg [36:0] oldr;
 reg sav_aw,sav_w,sav_b,sav_ar,sav_r,sav_last;
 reg [1:0] sav_bid,sav_bp,sav_rid,sav_rp;reg [31:0] sav_data;
 reg [2047:0] vectors,wave;
 task automatic fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"AXI4 mismatch at batch %0d cycle %0d",checks,cycles);end endtask
 always @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin wc=0;rc=0;bs=0;rs=0;end
   else begin
     if((^{awready,wready,bvalid,arready,rvalid})===1'bx)fail("AXI4_PROTOCOL");
     if(bs && (!bvalid || {bid,bresp}!==oldb))fail("AXI4_PROTOCOL");
     if(rs && (!rvalid || {rid,rresp,rlast,rdata}!==oldr))fail("AXI4_PROTOCOL");
     if(bvalid && wc==0)fail("AXI4_PROTOCOL");
     if(rvalid && rc==0)fail("AXI4_PROTOCOL");
     wc=wc+(awvalid&&awready)-(bvalid&&bready);
     rc=rc+(arvalid&&arready)-(rvalid&&rready&&rlast);
     if(wc<0 || wc>2 || rc<0 || rc>2)fail("AXI4_PROTOCOL");
     if(wc==2)$display("COVER outstanding/write-two");
     if(rc==2)$display("COVER outstanding/read-two");
     bs=bvalid&&!bready;oldb={bid,bresp};rs=rvalid&&!rready;oldr={rid,rresp,rlast,rdata};
     if(bs)$display("COVER stall/b");if(rs)$display("COVER stall/r");
     if(count_enable)begin
       if(bvalid&&bready)begin writes=writes+1;if(bresp!=0)errors=errors+1;end
       if(rvalid&&rready)begin read_beats=read_beats+1;if(rlast)begin reads=reads+1;if(rresp!=0)errors=errors+1;end end
       if(wvalid&&wready)write_beats=write_beats+1;
     end
   end
 end
 task tick;begin
   #1;sav_aw=awready;sav_w=wready;sav_b=bvalid;sav_ar=arready;sav_r=rvalid;
   sav_bid=bid;sav_bp=bresp;sav_rid=rid;sav_rp=rresp;sav_data=rdata;sav_last=rlast;
   @(posedge clk);#1;cycles=cycles+1;if(cycles>1000000)fail("AXI4_TIMEOUT");@(negedge clk);
 end endtask
 task clear_inputs;begin awvalid=0;wvalid=0;arvalid=0;bready=0;rready=0;end endtask
 task reset_bus;begin clear_inputs();rst_n=0;tick();rst_n=1;tick();
   if(bvalid || rvalid || !awready || !arready || wready)fail("AXI4_RESET");
 end endtask
 task send_aw(input integer address,input integer beats,input integer ident,input integer size,input integer burst);
   integer guard;begin
     awvalid=1;awaddr=address;awlen=beats-1;awid=ident;awsize=size;awburst=burst;guard=0;
     begin: wait_aw forever begin tick();guard=guard+1;if(sav_aw)disable wait_aw;if(guard>300)fail("AXI4_TIMEOUT");end end
     awvalid=0;
   end
 endtask
 task send_ar(input integer address,input integer beats,input integer ident,input integer size,input integer burst);
   integer guard;begin
     arvalid=1;araddr=address;arlen=beats-1;arid=ident;arsize=size;arburst=burst;guard=0;
     begin: wait_ar forever begin tick();guard=guard+1;if(sav_ar)disable wait_ar;if(guard>300)fail("AXI4_TIMEOUT");end end
     arvalid=0;
   end
 endtask
 task send_w(input integer data,input integer strobe,input integer last);
   integer guard;begin
     wvalid=1;wdata=data;wstrb=strobe;wlast=last;guard=0;
     begin: wait_w forever begin tick();guard=guard+1;if(sav_w)disable wait_w;if(guard>300)fail("AXI4_TIMEOUT");end end
     wvalid=0;
   end
 endtask
 function [3:0] strobes(input integer mode,input integer index);
   begin case(mode)0:strobes=15;1:strobes=5;2:strobes=0;default:strobes=1<<(index%4);endcase end
 endfunction
 task await_b(input integer ident,input integer error);
   integer guard;begin
     bready=1;guard=0;
     begin: wait_b forever begin tick();guard=guard+1;
       if(sav_b)begin
         if(sav_bid!==ident[1:0])fail("AXI4_ID");
         if(sav_bp!==(error ? 2'b10:2'b00))fail("AXI4_RESPONSE");
         if(error)$display("COVER response/error");else $display("COVER response/okay");disable wait_b;
       end
       if(guard>300)fail("AXI4_TIMEOUT");
     end end
     bready=0;
   end
 endtask
 task await_r(input integer ident,input integer beats,input integer error,input integer offset,input integer stall);
   integer guard,index,s;begin
     for(index=0;index<beats;index=index+1)begin
       rready=0;for(s=0;s<stall;s=s+1)tick();rready=1;guard=0;
       begin: wait_r forever begin tick();guard=guard+1;
         if(sav_r)begin
           if(sav_rid!==ident[1:0])fail("AXI4_ID");
           if(sav_last!==(index==beats-1))fail("AXI4_LAST");
           if(sav_rp!==(error ? 2'b10:2'b00))fail("AXI4_RESPONSE");
           if(sav_data!==v[14+offset+index])fail("AXI4_DATA");
           disable wait_r;
         end
         if(guard>300)fail("AXI4_TIMEOUT");
       end end
     end
     rready=0;
   end
 endtask
 initial begin
   if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))fail("AXI4_INPUT");
   $dumpfile(wave);$dumpvars(0,axi4_tb);@(negedge clk);reset_bus();
   // Reset queued addresses, an incomplete write burst, and a stalled read response.
   send_aw(0,4,1,2,1);send_aw(64,4,2,2,1);send_w(32'hffffffff,15,0);
   send_ar(0,4,1,2,1);send_ar(64,4,2,2,1);repeat(4)tick();
   if(!rvalid || awready || arready)fail("AXI4_RESET");reset_bus();
   // Reset a completed write awaiting BREADY and a read awaiting RREADY.
   send_aw(0,1,1,2,1);send_w(1,15,1);send_ar(0,1,1,2,1);repeat(4)tick();
   if(!bvalid || !rvalid)fail("AXI4_RESET");reset_bus();$display("COVER reset/active");
   // A master may assert WVALID before AWVALID; this target waits for the address.
   wvalid=1;wdata=32'h12345678;wstrb=15;wlast=1;repeat(3)tick();
   if(wready)fail("AXI4_PROTOCOL");send_aw(0,1,1,2,1);send_w(32'h12345678,15,1);
   await_b(1,0);$display("COVER channel/w-before-aw");reset_bus();
   // Read and write directions overlap. A stalled read must retain its snapshot.
   send_aw(0,1,1,2,1);send_w(32'h12345678,15,1);send_ar(0,1,3,2,1);repeat(3)tick();
   if(!rvalid)fail("AXI4_PROTOCOL");
   send_aw(0,1,2,2,1);send_w(32'h87654321,15,1);repeat(3)tick();
   if(rid!==2'b11)fail("AXI4_ID");if(rlast!==1'b1)fail("AXI4_LAST");
   if(rdata!==32'h12345678)fail("AXI4_DATA");
   rready=1;tick();rready=0;await_b(1,0);await_b(2,0);
   $display("COVER concurrency/r-held-during-write");reset_bus();
   count_enable=1;fd=$fopen(vectors,"r");if(!fd)fail("AXI4_INPUT");
   while(!$feof(fd))begin
     n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],v[16],v[17],v[18],v[19],v[20],v[21]);
     if(n!=22)fail("AXI4_INPUT");
     send_aw(v[0],v[2],v[4],v[10],v[11]);send_aw(v[1],v[3],v[5],v[10],v[11]);
     if(awready)fail("AXI4_PROTOCOL");
     for(q=0;q<2;q=q+1)begin
       for(beat=0;beat<v[2+q];beat=beat+1)begin
         for(k=0;k<v[9];k=k+1)tick();
         send_w((v[6] ^ (q ? 32'h5a5a5a5a:0))+32'h01030507*beat,strobes(v[7],beat),beat==v[2+q]-1);
       end
     end
     repeat(v[8])tick();await_b(v[4],v[12]);await_b(v[5],v[13]);
     send_ar(v[0],v[2],v[4],v[10],v[11]);send_ar(v[1],v[3],v[5],v[10],v[11]);
     if(arready)fail("AXI4_PROTOCOL");
     await_r(v[4],v[2],v[12],0,v[8]);await_r(v[5],v[3],v[13],v[2],v[8]);
     $display("COVER burst/beats%0d",v[2]);$display("COVER burst/beats%0d",v[3]);
     $display("COVER id/%0d",v[4]);$display("COVER id/%0d",v[5]);
     if(v[4]==v[5])$display("COVER id/repeated");
     $display("COVER strobe/mode%0d",v[7]);
     if(v[0]==4080 && !v[12])$display("COVER boundary/4k-legal");
     if(v[0]==4092 && v[12])$display("COVER boundary/4k-rejected");
     if(v[8]>=64)$display("COVER stall/long-recovery");
     checks=checks+1;
   end
   repeat(3)tick();if(bvalid || rvalid || wc!=0 || rc!=0)fail("AXI4_PROTOCOL");
   $display("COVER reset/recovery");
   $display("COUNT writes=%0d",writes);$display("COUNT reads=%0d",reads);
   $display("COUNT write_beats=%0d",write_beats);$display("COUNT read_beats=%0d",read_beats);$display("COUNT errors=%0d",errors);
   $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
