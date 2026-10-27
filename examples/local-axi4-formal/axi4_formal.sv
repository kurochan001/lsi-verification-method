module axi4_formal #(parameter MEM_BYTES=16,MUTATION=0,CHECK_DATA=0,AUXILIARY=1,LOCK_RESET=0,SERIAL_DATA=0)(
 input wire clk,rst_n,awvalid,wvalid,wlast,bready,arvalid,rready,
 input wire [$clog2(MEM_BYTES)-1:0] aw_address,ar_address,input wire aw_length,ar_length,
 input wire [1:0] awid,arid,input wire [31:0] wdata,input wire [3:0] wstrb
);
 wire [12:0] awaddr=aw_address,araddr=ar_address;wire [7:0] awlen=aw_length,arlen=ar_length;
 wire awready,wready,bvalid,arready,rvalid,rlast;wire [1:0] bid,bresp,rid,rresp,formal_wc,formal_rc,formal_wqueued;wire [31:0] rdata;
 axi4_ram #(.MEM_BYTES(MEM_BYTES),.MUTATION(MUTATION),.CHECK_INVARIANTS(AUXILIARY),.ABSTRACT_DATA(!CHECK_DATA)) dut(
  .clk(clk),.rst_n(rst_n),.awvalid(awvalid),.awaddr(awaddr),.awlen(awlen),.awsize(3'd2),.awburst(2'd1),.awid(awid),.awready(awready),
  .wvalid(wvalid),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.wready(wready),.bvalid(bvalid),.bready(bready),.bid(bid),.bresp(bresp),
  .arvalid(arvalid),.araddr(araddr),.arlen(arlen),.arsize(3'd2),.arburst(2'd1),.arid(arid),.arready(arready),
  .rvalid(rvalid),.rready(rready),.rdata(rdata),.rid(rid),.rresp(rresp),.rlast(rlast),.formal_wc(formal_wc),.formal_rc(formal_rc),.formal_wqueued(formal_wqueued));
 reg past_valid=0,recovering=0;reg [2:0] write_credit,read_credit;
 reg [12:0] write_address[0:1],read_address[0:1];reg [7:0] write_length[0:1],read_length[0:1];
 reg [1:0] write_id[0:1],read_id[0:1];reg wt,wh,bh,rt,rh;reg [7:0] wb,rb;
 (* anyconst *)reg [$clog2(MEM_BYTES)-1:0] watched_byte;
 reg [7:0] expected_byte,snapshot;reg compare_snapshot;
 wire expected_last=rb==read_length[rh];
 wire [13:0] write_location=write_address[wh]+4*wb,read_location=read_address[rh]+4*rb;
 always @(posedge clk)begin
  past_valid<=1;
  if(!past_valid)as_initial_reset:assume(!rst_n);
  if(past_valid && rst_n && $past(rst_n))begin
   if($past(awvalid && !awready))as_aw_hold:assume(awvalid && {awaddr,awlen,awid}==$past({awaddr,awlen,awid}));
   if($past(wvalid && !wready))as_w_hold:assume(wvalid && {wdata,wstrb,wlast}==$past({wdata,wstrb,wlast}));
   if($past(arvalid && !arready))as_ar_hold:assume(arvalid && {araddr,arlen,arid}==$past({araddr,arlen,arid}));
  end
  if(!rst_n)begin
   if(past_valid && (write_credit!=0 || read_credit!=0))recovering<=1;
   write_credit<=0;read_credit<=0;wt<=0;wh<=0;bh<=0;rt<=0;rh<=0;wb<=0;rb<=0;expected_byte<=0;snapshot<=0;compare_snapshot<=0;
   for(integer i=0;i<2;i=i+1)begin write_address[i]<=0;read_address[i]<=0;write_length[i]<=0;read_length[i]<=0;write_id[i]<=0;read_id[i]<=0;end
  end else begin
   write_credit<=write_credit+int'(awvalid&&awready)-int'(bvalid&&bready);
   read_credit<=read_credit+int'(arvalid&&arready)-int'(rvalid&&rready&&rlast);
   if(awvalid&&awready)begin write_address[wt]<=awaddr;write_length[wt]<=awlen;write_id[wt]<=awid;wt<=!wt;end
   if(arvalid&&arready)begin read_address[rt]<=araddr;read_length[rt]<=arlen;read_id[rt]<=arid;rt<=!rt;end
   if(wvalid&&wready)begin
    for(integer lane=0;lane<4;lane=lane+1)if(wstrb[lane] && write_location+lane==watched_byte)expected_byte<=wdata[8*lane+:8];
    if(wb==write_length[wh])begin wh<=!wh;wb<=0;end else wb<=wb+1;
   end
   if(bvalid&&bready)bh<=!bh;
   if(!rvalid && read_credit!=0)begin snapshot<=expected_byte;compare_snapshot<=read_location/4==watched_byte/4;end
   if(rvalid&&rready)begin
    if(expected_last)begin rh<=!rh;rb<=0;end else rb<=rb+1;
    recovering<=0;
   end
  end
  if(past_valid)begin
   if(!rst_n)ap_reset:assert(!bvalid && !rvalid);
   if(rst_n && $past(rst_n && bvalid && !bready))ap_b_hold:assert(bvalid && {bid,bresp}==$past({bid,bresp}));
   if(rst_n && $past(rst_n && rvalid && !rready))ap_r_hold:assert(rvalid && {rid,rdata,rresp,rlast}==$past({rid,rdata,rresp,rlast}));
   cp_two_write:cover(rst_n && write_credit==2);
   cp_two_read:cover(rst_n && read_credit==2);
   cp_w_first:cover(rst_n && wvalid && write_credit==0 && !awvalid);
   cp_b_stall:cover(rst_n && bvalid && !bready);
   cp_r_stall:cover(rst_n && rvalid && !rready);
   cp_burst:cover(rst_n && rvalid && rready && expected_last && read_length[rh]==1);
   cp_zero_strobe:cover(rst_n && wvalid && wready && wstrb==0);
   cp_reset_pending:cover(!rst_n && (write_credit!=0 || read_credit!=0));
   cp_recovery:cover(rst_n && recovering && rvalid && rready);
  end
 end
 generate if(AUXILIARY)begin
  always @(posedge clk)if(past_valid && rst_n)begin
   ai_credit_match:assert(write_credit==formal_wc && read_credit==formal_rc);
   ap_credit_bounds:assert(write_credit<=2 && read_credit<=2);
  end
 end endgenerate
 generate if(SERIAL_DATA)begin
  always @(posedge clk)if(rst_n)begin
   as_serial_channels:assume(!(awvalid && arvalid));
   as_serial_aw:assume(!awvalid || (write_credit==0 && read_credit==0));
   as_serial_ar:assume(!arvalid || (write_credit==0 && read_credit==0));
  end
 end endgenerate
 generate if(CHECK_DATA)begin
  always @(posedge clk)if(past_valid && rst_n)begin
   as_aw_legal:assume(awlen<=1 && awaddr[1:0]==0 && {1'b0,awaddr}+(awlen+1)*4<=MEM_BYTES);
   as_ar_legal:assume(arlen<=1 && araddr[1:0]==0 && {1'b0,araddr}+(arlen+1)*4<=MEM_BYTES);
   if(wvalid && wready)as_wlast:assume(wlast==(wb==write_length[wh]));

   if(bvalid || rvalid)ap_ids:assert((!bvalid || (write_credit!=0 && bid==write_id[bh])) && (!rvalid || (read_credit!=0 && rid==read_id[rh])));
   if(rvalid)begin
    ap_last:assert(rlast==expected_last);
    if(compare_snapshot)ap_data:assert(rdata[8*(watched_byte%4)+:8]==snapshot);
   end
   ap_response:assert((!bvalid || bresp==0) && (!rvalid || rresp==0));
  end
 end endgenerate
 generate if(LOCK_RESET)always @(posedge clk)as_lock_reset:assume(!rst_n);endgenerate
endmodule
