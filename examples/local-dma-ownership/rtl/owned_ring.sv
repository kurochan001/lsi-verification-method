module owned_ring #(parameter DEPTH=2,MUTATION=0)(
 input wire clk,rst_n,host_valid,input wire[2:0]host_op,host_slot,input wire[12:0]host_src,host_dst,input wire[5:0]host_words,output wire host_ready,host_error,
 output wire busy,irq,output reg[7:0]retired,output reg[2:0]head,output wire[2*DEPTH-1:0]owners,output reg[DEPTH-1:0]errors,
 output wire arvalid,input wire arready,output wire[12:0]araddr,output wire[7:0]arlen,output wire[1:0]arid,input wire rvalid,output wire rready,input wire[31:0]rdata,input wire[1:0]rid,rresp,input wire rlast,
 output wire awvalid,input wire awready,output wire[12:0]awaddr,output wire[7:0]awlen,output wire[1:0]awid,output wire wvalid,input wire wready,output wire[31:0]wdata,output wire[3:0]wstrb,output wire wlast,input wire bvalid,output wire bready,input wire[1:0]bid,bresp
);
 reg[1:0]owner[0:DEPTH-1];reg[12:0]src[0:DEPTH-1],dst[0:DEPTH-1];reg[5:0]words[0:DEPTH-1];reg active,enabled,start_copy,seen_busy,irq_pending;
 wire copy_busy,copy_done,copy_error,copy_aborted,copy_irq;wire[2:0]copy_completed;
 wire carvalid,carready,crvalid,crready,crlast;wire[12:0]caraddr;wire[7:0]carlen;wire[1:0]carid,crid,crresp;wire[31:0]crdata;
 reg descriptor_active;reg[2:0]descriptor_slot;reg[1:0]descriptor_beat;
 wire descriptor_request=caraddr>=6144 && caraddr<6144+16*DEPTH;
 assign arvalid=carvalid && !descriptor_request;assign araddr=caraddr;assign arlen=carlen;assign arid=carid;assign carready=descriptor_request ? !descriptor_active:arready;
 assign crvalid=descriptor_active ? 1'b1:rvalid;assign crdata=descriptor_active ? (descriptor_beat==0 ? {19'b0,src[descriptor_slot]}:descriptor_beat==1 ? {19'b0,dst[descriptor_slot]}:descriptor_beat==2 ? {26'b0,words[descriptor_slot]}:32'd1):rdata;
 assign crid=descriptor_active ? 0:rid;assign crresp=descriptor_active ? 0:rresp;assign crlast=descriptor_active ? descriptor_beat==3:rlast;assign rready=crready && !descriptor_active;
 descriptor_dma #(.DEPTH(DEPTH),.MUTATION(MUTATION==4 ? 4:0))copy(.clk(clk),.rst_n(rst_n),.start(start_copy),.abort_req(1'b0),.start_head(head),.start_count(3'd1),.busy(copy_busy),.done(copy_done),.error(copy_error),.aborted(copy_aborted),.irq(copy_irq),.completed(copy_completed),.arvalid(carvalid),.arready(carready),.araddr(caraddr),.arlen(carlen),.arid(carid),.rvalid(crvalid),.rready(crready),.rdata(crdata),.rid(crid),.rresp(crresp),.rlast(crlast),.awvalid(awvalid),.awready(awready),.awaddr(awaddr),.awlen(awlen),.awid(awid),.wvalid(wvalid),.wready(wready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.bvalid(bvalid),.bready(bready),.bid(bid),.bresp(bresp));
 for(genvar i=0;i<DEPTH;i=i+1)assign owners[2*i+:2]=owner[i];
 assign host_ready=rst_n;
 assign host_error=host_valid && (!(host_op==1 || host_op==2 || host_op==3 || host_op==4) || ((host_op==1 || host_op==2) && (host_slot>=DEPTH || (host_op==1 ? (owner[host_slot]!=0 && MUTATION!=1):owner[host_slot]!=3))));
 assign busy=active;assign irq=irq_pending;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin active<=0;enabled<=0;start_copy<=0;seen_busy<=0;irq_pending<=0;retired<=0;head<=0;errors<=0;descriptor_active<=0;descriptor_slot<=0;descriptor_beat<=0;for(integer i=0;i<DEPTH;i=i+1)begin owner[i]<=0;src[i]<=0;dst[i]<=0;words[i]<=0;end end
 else begin
 start_copy<=0;
 if(carvalid && carready && descriptor_request)begin descriptor_active<=1;descriptor_slot<=(caraddr-6144)/16;descriptor_beat<=0;end
 if(descriptor_active && crready)begin if(descriptor_beat==3)descriptor_active<=0;else descriptor_beat<=descriptor_beat+1'b1;end
 if(host_valid && host_ready && !host_error)case(host_op)
 1:begin owner[host_slot]<=1;src[host_slot]<=host_src;dst[host_slot]<=host_dst;words[host_slot]<=host_words;errors[host_slot]<=0;end
 2:begin if(MUTATION!=2)owner[host_slot]<=0;errors[host_slot]<=0;end
 3:enabled<=1;4:irq_pending<=0;default:;endcase
 if(!active && enabled && owner[head]==1)begin owner[head]<=2;active<=1;seen_busy<=0;start_copy<=1;end
 if(active)begin
 if(copy_busy)seen_busy<=1;
 if(seen_busy && copy_done && !copy_busy)begin owner[head]<=3;errors[head]<=copy_error || copy_aborted;retired<=retired+1'b1;head<=(head+(MUTATION==3 ? 2:1))%DEPTH;active<=0;seen_busy<=0;irq_pending<=1;end
 end end end endmodule
