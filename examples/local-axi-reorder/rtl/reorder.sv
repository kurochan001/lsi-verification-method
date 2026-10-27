module reorder #(parameter MUTATION=0,SLOTS=2)(
 input wire release_enable,
 input wire clk,rst_n,
 input wire awvalid,input wire [12:0] awaddr,input wire [7:0] awlen,
 input wire [2:0] awsize,input wire [1:0] awburst,awid,output wire awready,
 input wire wvalid,input wire [31:0] wdata,input wire [3:0] wstrb,input wire wlast,output wire wready,
 output wire bvalid,input wire bready,output wire [1:0] bid,bresp,
 input wire arvalid,input wire [12:0] araddr,input wire [7:0] arlen,
 input wire [2:0] arsize,input wire [1:0] arburst,arid,output wire arready,
 output reg rvalid,input wire rready,output reg [31:0] rdata,output reg [1:0] rid,rresp,output wire rlast
);
 wire mem_awready,mem_wready,mem_arready,mem_bvalid,mem_rvalid,mem_rlast;wire[1:0]mem_bid,mem_bresp,mem_rid,mem_rresp;wire[31:0]mem_rdata;
 wire mem_bready,mem_rready;integer wc,rc;
 assign awready=mem_awready && wc<SLOTS;assign wready=mem_wready;assign arready=mem_arready && rc<SLOTS;
 axi4_ram memory(.clk(clk),.rst_n(rst_n),.awvalid(awvalid && wc<SLOTS),.awready(mem_awready),.awaddr(awaddr),.awlen(awlen),.awsize(awsize),.awburst(awburst),.awid(awid),.wvalid(wvalid),.wready(mem_wready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.bvalid(mem_bvalid),.bready(mem_bready),.bid(mem_bid),.bresp(mem_bresp),.arvalid(arvalid && rc<SLOTS),.arready(mem_arready),.araddr(araddr),.arlen(arlen),.arsize(arsize),.arburst(arburst),.arid(arid),.rvalid(mem_rvalid),.rready(mem_rready),.rdata(mem_rdata),.rid(mem_rid),.rresp(mem_rresp),.rlast(mem_rlast));
 reg bb[0:SLOTS-1],rb[0:SLOTS-1],complete[0:SLOTS-1];reg[1:0]bi[0:SLOTS-1],br[0:SLOTS-1],ri[0:SLOTS-1],rr[0:SLOTS-1];
 reg[31:0]rd[0:SLOTS-1][0:3];integer bt[0:SLOTS-1],rt[0:SLOTS-1],length[0:SLOTS-1];
 integer bused,rused,bhold,rhold,rbeat,capture,cbeat,bfree,rfree,bpick,rpick;reg eligible;
 always @*begin
 bfree=-1;rfree=-1;bpick=-1;rpick=-1;eligible=0;bused=0;rused=0;
 for(integer i=0;i<SLOTS;i=i+1)begin
 if(!bb[i])bfree=i;else bused=bused+1;if(!rb[i])rfree=i;else rused=rused+1;
 eligible=bb[i];for(integer j=0;j<SLOTS;j=j+1)if(MUTATION!=3 && bb[j] && bi[j]==bi[i] && bt[j]<bt[i])eligible=0;
 if(eligible && (bpick<0 || bt[i]>bt[bpick]))bpick=i;
 eligible=rb[i] && complete[i];for(integer j=0;j<SLOTS;j=j+1)if(MUTATION!=3 && rb[j] && ri[j]==ri[i] && rt[j]<rt[i])eligible=0;
 if(eligible && (rpick<0 || rt[i]>rt[rpick]))rpick=i;
 end end
 assign mem_bready=rst_n && bfree>=0;assign mem_rready=rst_n && (capture>=0 || rfree>=0);
 assign bvalid=rst_n && bhold>=0;assign bid=bhold>=0 ? bi[bhold]^(MUTATION==1 ? 2'd1:0):0;assign bresp=bhold>=0 ? br[bhold]:0;
 always @*begin rvalid=rst_n && rhold>=0;rid=rhold>=0 ? ri[rhold]^(MUTATION==2 ? 2'd1:0):0;rresp=rhold>=0 ? rr[rhold]:0;rdata=rhold>=0 ? rd[rhold][rbeat]^(MUTATION==4 ? 32'd1:0):0;end
 assign rlast=rhold>=0 && rbeat==length[rhold]-1;
 integer slot;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin
 wc<=0;rc<=0;bhold<=-1;rhold<=-1;rbeat<=0;capture<=-1;cbeat<=0;
 for(integer i=0;i<SLOTS;i=i+1)begin bb[i]<=0;rb[i]<=0;complete[i]<=0;bi[i]<=0;ri[i]<=0;br[i]<=0;rr[i]<=0;bt[i]<=0;rt[i]<=0;length[i]<=0;end
 end else begin
 case({awvalid&&awready,bvalid&&bready})2'b10:wc<=wc+1;2'b01:wc<=wc-1;default:;endcase
 case({arvalid&&arready,rvalid&&rready&&rlast})2'b10:rc<=rc+1;2'b01:rc<=rc-1;default:;endcase
 if(mem_bvalid && mem_bready)begin bb[bfree]<=1;bi[bfree]<=mem_bid;br[bfree]<=mem_bresp;bt[bfree]<=bused-(bvalid && bready ? 1:0);end
 if(bhold<0 && release_enable && bpick>=0)bhold<=bpick;
 // Compact relative ranks on retirement, so long runs cannot overflow a ticket.
 if(bvalid && bready)begin
 for(integer i=0;i<SLOTS;i=i+1)if(bb[i] && bt[i]>bt[bhold])bt[i]<=bt[i]-1;
 bb[bhold]<=0;bhold<=-1;end
 if(mem_rvalid && mem_rready)begin
 slot=capture>=0 ? capture:rfree;
 if(capture<0)begin rb[slot]<=1;complete[slot]<=0;ri[slot]<=mem_rid;rr[slot]<=mem_rresp;rt[slot]<=rused-(rvalid && rready && rlast ? 1:0);end
 rd[slot][cbeat]<=mem_rdata;
 if(mem_rlast)begin length[slot]<=cbeat+1;complete[slot]<=1;capture<=-1;cbeat<=0;end
 else begin capture<=slot;cbeat<=cbeat+1;end
 end
 if(rhold<0 && release_enable && rpick>=0)begin rhold<=rpick;rbeat<=0;end
 if(rvalid && rready)begin if(rlast)begin
 for(integer i=0;i<SLOTS;i=i+1)if(rb[i] && rt[i]>rt[rhold])rt[i]<=rt[i]-1;
 rb[rhold]<=0;complete[rhold]<=0;rhold<=-1;rbeat<=0;end else rbeat<=rbeat+1;end
 end end endmodule
