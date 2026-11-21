`timescale 1ns/1ps
// Drives one request row at a time from the vector file and checks every response beat against it.
// All sampling and all protocol checks sit in tick(), so no clocked block races with the stimulus.
module axi4_full_tb;
 parameter MUTATION=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,awvalid=0,wvalid=0,wlast=0,bready=0,arvalid=0,rready=0,awlock=0,arlock=0;
 reg [12:0] awaddr=0,araddr=0;
 reg [7:0] awlen=0,arlen=0;
 reg [2:0] awsize=0,arsize=0;
 reg [1:0] awburst=0,arburst=0,awid=0,arid=0;
 reg [31:0] wdata=0;reg [3:0] wstrb=0;
 wire awready,wready,bvalid,arready,rvalid,rlast;
 wire [1:0] bid,bresp,rid,rresp;wire [31:0] rdata;
 axi4_full_ram #(.MUTATION(MUTATION)) dut(.*);
 // Slot 0 is the request in progress, slot 1 the one whose address is offered early.
 integer row[0:11],hdr[0:23],bt[0:1535];
 integer fd,n,checks=0,cycles=0,pre_sent=0;
 integer writes=0,reads=0,write_beats=0,read_beats=0,slverr=0,exokay=0,wleft=0;
 reg count_enable=0;
 reg sav_aw,sav_w,sav_b,sav_ar,sav_r,sav_last;
 reg [1:0] sav_bid,sav_bp,sav_rid,sav_rp;reg [31:0] sav_data;
 reg h_aw,h_w,h_b,h_ar,h_r;
 reg wbusy=0,wphase=0,rbusy=0,bstalled=0,rstalled=0,bg_aw=0,bg_ar=0;
 reg seen_sb=0,seen_sr=0,seen_aw=0,seen_ar=0;
 reg [3:0] old_b;reg [36:0] old_r;
 string vectors,wave,tag_name;
 task automatic fail(input string label);begin
   $display("CHECK_FAIL %s",label);$fatal(1,"AXI4 mismatch at row %0d cycle %0d",checks,cycles);
 end endtask
 task tick;begin
   #1;sav_aw=awready;sav_w=wready;sav_b=bvalid;sav_ar=arready;sav_r=rvalid;
   sav_bid=bid;sav_bp=bresp;sav_rid=rid;sav_rp=rresp;sav_data=rdata;sav_last=rlast;
   if((^{sav_aw,sav_w,sav_b,sav_ar,sav_r})===1'bx)fail("AXF_PROTOCOL");
   if(sav_b && (^{sav_bid,sav_bp})===1'bx)fail("AXF_PROTOCOL");
   if(sav_r && (^{sav_rid,sav_rp,sav_last})===1'bx)fail("AXF_PROTOCOL");
   if(bstalled && (!sav_b || {sav_bid,sav_bp}!==old_b))fail("AXF_PROTOCOL");
   if(rstalled && (!sav_r || {sav_rid,sav_rp,sav_last,sav_data}!==old_r))fail("AXF_PROTOCOL");
   if(sav_b && !(wbusy && !wphase))fail("AXF_PROTOCOL");
   if(sav_r && !rbusy)fail("AXF_PROTOCOL");
   // One transaction per direction: no new address while one is in flight, data only in its phase.
   if(wbusy && sav_aw)fail("AXF_HANDSHAKE");
   if(rbusy && sav_ar)fail("AXF_HANDSHAKE");
   if(!wphase && sav_w)fail("AXF_HANDSHAKE");
   h_aw=awvalid&&sav_aw;h_w=wvalid&&sav_w;h_b=sav_b&&bready;h_ar=arvalid&&sav_ar;h_r=sav_r&&rready;
   bstalled=sav_b&&!bready;old_b={sav_bid,sav_bp};rstalled=sav_r&&!rready;old_r={sav_rid,sav_rp,sav_last,sav_data};
   if(bstalled && !seen_sb)begin seen_sb=1;$display("COVER stall/b");end
   if(rstalled && !seen_sr)begin seen_sr=1;$display("COVER stall/r");end
   if(awvalid && !sav_aw && wbusy && !seen_aw)begin seen_aw=1;$display("COVER handshake/aw-held-busy");end
   if(arvalid && !sav_ar && rbusy && !seen_ar)begin seen_ar=1;$display("COVER handshake/ar-held-busy");end
   @(posedge clk);#1;cycles=cycles+1;if(cycles>2000000)fail("AXF_TIMEOUT");
   if(h_aw)begin wbusy=1;wphase=1;wleft=awlen+1;end
   if(h_w)begin wleft=wleft-1;if(wleft==0)wphase=0;end
   if(h_b)wbusy=0;
   if(h_ar)rbusy=1;
   if(h_r && sav_last)rbusy=0;
   if(count_enable)begin
     if(h_w)write_beats=write_beats+1;
     if(h_r)read_beats=read_beats+1;
     if(h_b)begin writes=writes+1;if(sav_bp===2'b10)slverr=slverr+1;if(sav_bp===2'b01)exokay=exokay+1;end
     if(h_r && sav_last)begin reads=reads+1;if(sav_rp===2'b10)slverr=slverr+1;if(sav_rp===2'b01)exokay=exokay+1;end
   end
   @(negedge clk);
   if(bg_aw && h_aw)begin awvalid=0;bg_aw=0;end
   if(bg_ar && h_ar)begin arvalid=0;bg_ar=0;end
 end endtask
 task reset_bus;begin
   awvalid=0;wvalid=0;arvalid=0;bready=0;rready=0;bg_aw=0;bg_ar=0;pre_sent=0;
   wbusy=0;wphase=0;rbusy=0;bstalled=0;rstalled=0;wleft=0;rst_n=0;tick();rst_n=1;tick();
   if(bvalid!==1'b0 || rvalid!==1'b0 || awready!==1'b1 || arready!==1'b1 || wready!==1'b0)fail("AXF_RESET");
 end endtask
 task drive_aw(input integer s);begin
   awaddr=hdr[s*12+1];awlen=hdr[s*12+2]-1;awsize=hdr[s*12+3];awburst=hdr[s*12+4];awid=hdr[s*12+5];awlock=hdr[s*12+6];awvalid=1;
 end endtask
 task drive_ar(input integer s);begin
   araddr=hdr[s*12+1];arlen=hdr[s*12+2]-1;arsize=hdr[s*12+3];arburst=hdr[s*12+4];arid=hdr[s*12+5];arlock=hdr[s*12+6];arvalid=1;
 end endtask
 task send_aw;integer guard;begin
   drive_aw(0);guard=0;
   begin: wait_aw forever begin tick();guard=guard+1;if(h_aw)disable wait_aw;if(guard>600)fail("AXF_TIMEOUT");end end
   awvalid=0;
 end endtask
 task send_ar;integer guard;begin
   drive_ar(0);guard=0;
   begin: wait_ar forever begin tick();guard=guard+1;if(h_ar)disable wait_ar;if(guard>600)fail("AXF_TIMEOUT");end end
   arvalid=0;
 end endtask
 task send_w(input integer k);integer guard;begin
   wvalid=1;wdata=bt[k*3];wstrb=bt[k*3+1];wlast=bt[k*3+2];guard=0;
   begin: wait_w forever begin tick();guard=guard+1;if(h_w)disable wait_w;if(guard>600)fail("AXF_TIMEOUT");end end
   wvalid=0;
 end endtask
 task read_row;begin
   n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8],row[9],row[10],row[11]);
   if(n!=12)fail("AXF_INPUT");
   checks=checks+1;
 end endtask
 // The header is in row[]; read the beat rows that belong to it.
 task load_slot(input integer s,input integer kind);integer i,k;begin
   if(row[0]!=kind)fail("AXF_INPUT");
   for(i=0;i<12;i=i+1)hdr[s*12+i]=row[i];
   for(k=0;k<hdr[s*12+2];k=k+1)begin
     read_row();if(row[0]!=kind+1)fail("AXF_INPUT");
     bt[s*768+k*3]=row[1];bt[s*768+k*3+1]=row[2];bt[s*768+k*3+2]=row[3];
   end
 end endtask
 task promote;integer i;begin
   for(i=0;i<12;i=i+1)hdr[i]=hdr[12+i];
   for(i=0;i<768;i=i+1)bt[i]=bt[768+i];
   pre_sent=1;
 end endtask
 task tag_cover(input integer tag);begin
   if(tag!=0)begin
     case(tag)
       1:tag_name="handshake/idle-ready";
       2:tag_name="wrap/start-mid";
       3:tag_name="wrap/start-top";
       4:tag_name="wrap/narrow";
       5:tag_name="fixed/last-beat-wins";
       6:tag_name="fixed/read-repeats";
       7:tag_name="strobe/partial";
       8:tag_name="strobe/zero";
       9:tag_name="strobe/outside-lanes";
       10:tag_name="boundary/4k-exact";
       11:tag_name="boundary/4k-cross-rejected";
       12:tag_name="boundary/4k-cross-by-one-byte";
       13:tag_name="boundary/unaligned-last-bytes";
       14:tag_name="boundary/memory-end";
       15:tag_name="error/reserved-burst";
       16:tag_name="error/size";
       17:tag_name="error/wrap-length";
       18:tag_name="error/wrap-unaligned";
       19:tag_name="error/fixed-length";
       20:tag_name="error/wlast-early";
       21:tag_name="error/wlast-missing";
       22:tag_name="error/no-write";
       23:tag_name="excl/success";
       24:tag_name="excl/second-write-fails";
       25:tag_name="excl/fail-other-write";
       26:tag_name="excl/adjacent-write-keeps";
       27:tag_name="excl/one-byte-overlap";
       28:tag_name="excl/fail-mismatch";
       29:tag_name="excl/other-id-attempt-keeps";
       30:tag_name="excl/race-loser";
       31:tag_name="excl/malformed-read";
       32:tag_name="excl/multi-beat";
       33:tag_name="excl/reset-clears";
       34:tag_name="excl/normal-read-keeps";
       35:tag_name="excl/error-read";
       36:tag_name="reset/vectors";
       default:fail("AXF_INPUT");
     endcase
     $display("COVER %s",tag_name);
   end
 end endtask
 task shape_cover(input integer write);integer width;string direction,name;begin
   if(write)direction="write";else direction="read";
   if(hdr[7]==0)name="okay";else if(hdr[7]==1)name="exokay";else name="slverr";
   $display("COVER resp/%s",name);
   if(hdr[7]!=2)begin
     width=1<<hdr[3];
     if(hdr[4]==0)name="fixed";else if(hdr[4]==1)name="incr";else name="wrap";
     $display("COVER burst/%s-%s",direction,name);
     if(hdr[3]==0)name="byte";else if(hdr[3]==1)name="half";else name="word";
     $display("COVER size/%s",name);
     if(hdr[4]==2)$display("COVER wrap/len%0d",hdr[2]);
     if(hdr[1]%width!=0)$display("COVER unaligned/%s",direction);
     if(hdr[2]==1)$display("COVER length/1");
     if(hdr[2]==256)$display("COVER length/256-%s",direction);
   end
 end endtask
 task do_write;integer k,guard,chain,first,s;reg [1:0] want;begin
   chain=hdr[10]&1;first=(hdr[10]>>1)&1;
   if(!pre_sent)begin
     if(first)begin
       // The data may arrive before the address; this target must wait for the address.
       wvalid=1;wdata=bt[0];wstrb=bt[1];wlast=bt[2];repeat(3)tick();$display("COVER channel/w-before-aw");
     end
     send_aw();
   end
   pre_sent=0;
   if(chain)begin read_row();load_slot(1,1);end
   for(k=0;k<hdr[2];k=k+1)begin
     if(!(first && k==0))for(s=0;s<hdr[8];s=s+1)tick();
     if(chain && k==0)begin drive_aw(1);bg_aw=1;end
     send_w(k);
   end
   bready=0;for(s=0;s<hdr[9];s=s+1)tick();bready=1;guard=0;want=hdr[7];
   begin: wait_b forever begin tick();guard=guard+1;
     if(h_b)begin
       if(sav_bid!==hdr[5][1:0])fail("AXF_ID");
       if(sav_bp!==want)fail((sav_bp===2'b01 || want==2'b01) ? "AXF_EXCL":"AXF_RESP");
       disable wait_b;
     end
     if(guard>600)fail("AXF_TIMEOUT");
   end end
   bready=0;shape_cover(1);tag_cover(hdr[11]);
   if(chain)begin
     guard=0;while(bg_aw)begin tick();guard=guard+1;if(guard>600)fail("AXF_TIMEOUT");end
     promote();
   end
 end endtask
 task do_read;integer k,guard,chain,s;reg [1:0] want;reg [31:0] expected,mask;begin
   chain=hdr[10]&1;want=hdr[7];
   if(!pre_sent)send_ar();
   pre_sent=0;
   if(chain)begin read_row();load_slot(1,3);end
   for(k=0;k<hdr[2];k=k+1)begin
     rready=0;for(s=0;s<hdr[8];s=s+1)tick();
     if(chain && k==0)begin drive_ar(1);bg_ar=1;end
     rready=1;guard=0;expected=bt[k*3];
     mask={{8{bt[k*3+1][3]}},{8{bt[k*3+1][2]}},{8{bt[k*3+1][1]}},{8{bt[k*3+1][0]}}};
     begin: wait_r forever begin tick();guard=guard+1;
       if(h_r)begin
         if(sav_rid!==hdr[5][1:0])fail("AXF_ID");
         if(sav_last!==bt[k*3+2][0])fail("AXF_LAST");
         if(sav_rp!==want)fail((sav_rp===2'b01 || want==2'b01) ? "AXF_EXCL":"AXF_RESP");
         if((sav_data&mask)!==(expected&mask))fail("AXF_DATA");
         // Lanes outside the beat are driven to zero by this target; anything else is a wrong lane.
         if((sav_data&~mask)!==32'd0)fail("AXF_LANE");
         disable wait_r;
       end
       if(guard>600)fail("AXF_TIMEOUT");
     end end
   end
   rready=0;shape_cover(0);tag_cover(hdr[11]);
   if(chain)begin
     guard=0;while(bg_ar)begin tick();guard=guard+1;if(guard>600)fail("AXF_TIMEOUT");end
     promote();
   end
 end endtask
 integer i;
 initial begin
   if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))fail("AXF_INPUT");
   $dumpfile(wave);$dumpvars(0,axi4_full_tb);@(negedge clk);reset_bus();
   // Reset in the middle of a write burst and with a read beat waiting for RREADY.
   for(i=0;i<24;i=i+1)hdr[i]=0;
   hdr[1]=64;hdr[2]=4;hdr[3]=2;hdr[4]=1;hdr[5]=1;bt[0]=32'h0badc0de;bt[1]=15;bt[2]=0;
   send_aw();send_w(0);send_ar();repeat(3)tick();
   if(rvalid!==1'b1 || wready!==1'b1)fail("AXF_RESET");
   reset_bus();$display("COVER reset/mid-burst");
   // Reset with a write response and a read response both waiting.
   hdr[2]=1;bt[2]=1;send_aw();send_w(0);send_ar();repeat(3)tick();
   if(bvalid!==1'b1 || rvalid!==1'b1)fail("AXF_RESET");
   reset_bus();$display("COVER reset/pending-response");
   // The resets must have cleared the word the first burst wrote: read it back.
   send_ar();rready=1;i=0;
   begin: first_read forever begin
     tick();i=i+1;if(h_r)begin if(sav_data!==32'd0)fail("AXF_RESET");disable first_read;end
     if(i>600)fail("AXF_TIMEOUT");
   end end
   rready=0;tick();
   count_enable=1;fd=$fopen(vectors,"r");if(!fd)fail("AXF_INPUT");
   while(!$feof(fd))begin
     if(!pre_sent)begin
       read_row();
       case(row[0])
         0:begin
           for(i=0;i<row[1];i=i+1)tick();
           if(awready!==1'b1 || arready!==1'b1 || wready!==1'b0)fail("AXF_HANDSHAKE");
           tag_cover(row[11]);
         end
         1:begin load_slot(0,1);do_write();end
         3:begin load_slot(0,3);do_read();end
         5:begin reset_bus();tag_cover(row[11]);end
         default:fail("AXF_INPUT");
       endcase
     end
     while(pre_sent)begin if(hdr[0]==1)do_write();else do_read();end
   end
   repeat(3)tick();if(bvalid!==1'b0 || rvalid!==1'b0 || wbusy || rbusy)fail("AXF_PROTOCOL");
   $display("COUNT writes=%0d",writes);$display("COUNT reads=%0d",reads);
   $display("COUNT write_beats=%0d",write_beats);$display("COUNT read_beats=%0d",read_beats);
   $display("COUNT slverr=%0d",slverr);$display("COUNT exokay=%0d",exokay);
   $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
