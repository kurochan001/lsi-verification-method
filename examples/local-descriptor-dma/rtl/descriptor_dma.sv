// Fixed ring of 16-byte descriptors at 0x1800: src,dst,words,flags(1=owned).
// Descriptor fetch and the existing copy engine share a serialized AXI4 read port.
module descriptor_dma #(parameter DEPTH=2,MUTATION=0)(
 input wire clk,rst_n,start,abort_req,input wire [2:0] start_head,start_count,
 output wire busy,irq,output reg done,error,aborted,output reg [2:0] completed,
 output wire arvalid,input wire arready,output wire [12:0] araddr,output wire [7:0] arlen,output wire [1:0] arid,
 input wire rvalid,output wire rready,input wire [31:0] rdata,input wire[1:0]rid,rresp,input wire rlast,
 output wire awvalid,input wire awready,output wire[12:0]awaddr,output wire[7:0]awlen,output wire[1:0]awid,
 output wire wvalid,input wire wready,output wire[31:0]wdata,output wire[3:0]wstrb,output wire wlast,
 input wire bvalid,output wire bready,input wire[1:0]bid,bresp
);
 localparam IDLE=0,FETCH_AR=1,FETCH_R=2,PROGRAM=3,POLL=4;
 reg[2:0]state,index,left;reg[1:0]beat,program_index;reg phase,wait_abort,abort_pending,abort_sent,fetch_error;
 reg[31:0]descriptor[0:2];wire copy_arvalid,copy_arready,copy_rready;wire[12:0]copy_araddr;wire[7:0]copy_arlen;wire[1:0]copy_arid;
 reg psel,penable,pwrite;reg[7:0]paddr;reg[31:0]pwdata;wire pready,pslverr,copy_irq;wire[31:0]prdata;
 wire need_abort=abort_pending && !abort_sent;
 apb_dma #(.MUTATION(MUTATION==4 ? 2:0)) copy_engine(.clk(clk),.rst_n(rst_n),.psel(psel),.penable(penable),.pwrite(pwrite),.paddr(paddr),.pwdata(pwdata),.pready(pready),.pslverr(pslverr),.prdata(prdata),.irq(copy_irq),
 .arvalid(copy_arvalid),.arready(copy_arready),.araddr(copy_araddr),.arlen(copy_arlen),.arid(copy_arid),
 .rvalid(rvalid && state==POLL),.rready(copy_rready),.rdata(rdata),.rid(rid),.rresp(rresp),.rlast(rlast),
 .awvalid(awvalid),.awready(awready),.awaddr(awaddr),.awlen(awlen),.awid(awid),.wvalid(wvalid),.wready(wready),.wdata(wdata),.wstrb(wstrb),.wlast(wlast),.bvalid(bvalid),.bready(bready),.bid(bid),.bresp(bresp));
 assign busy=state!=IDLE;assign irq=done && MUTATION!=3;
 assign arvalid=rst_n && (state==FETCH_AR || (state==POLL && copy_arvalid));
 assign araddr=state==FETCH_AR ? 13'd6144+16*index:copy_araddr;assign arlen=state==FETCH_AR ? 8'd3:copy_arlen;assign arid=state==FETCH_AR ? 0:copy_arid;
 assign copy_arready=arready && state==POLL;assign rready=rst_n && (state==FETCH_R || (state==POLL && copy_rready));
 always @*begin
 psel=0;penable=phase;pwrite=0;paddr=16;pwdata=0;
 if(state==PROGRAM && !(program_index==3 && !phase && (abort_pending || abort_req)))begin
 psel=1;pwrite=1;paddr=program_index==3 ? 12:4*program_index;pwdata=program_index==3 ? 1:descriptor[program_index];
 end
 if(state==POLL)begin psel=1;pwrite=phase ? wait_abort:need_abort;paddr=pwrite ? 12:16;pwdata=pwrite ? 2:0;end
 end
 task finish(input bad,input stopped);begin state<=IDLE;done<=1;error<=bad;aborted<=stopped;end endtask
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin
 state<=IDLE;index<=0;left<=0;beat<=0;program_index<=0;phase<=0;wait_abort<=0;abort_pending<=0;abort_sent<=0;fetch_error<=0;done<=0;error<=0;aborted<=0;completed<=0;
 for(integer i=0;i<3;i=i+1)descriptor[i]<=0;
 end else begin
 if(abort_req && busy)abort_pending<=1;
 case(state)
 IDLE:if(start)begin
 done<=0;error<=0;aborted<=0;completed<=0;index<=start_head;left<=start_count;abort_pending<=0;abort_sent<=0;
 if(start_head>=DEPTH || start_count>DEPTH)finish(1,0);else if(start_count==0)finish(0,0);else state<=FETCH_AR;
 end
 FETCH_AR:if(arready)begin state<=FETCH_R;beat<=0;fetch_error<=0;end
 FETCH_R:if(rvalid)begin
 if(beat<3)descriptor[beat]<=rdata;
 fetch_error<=fetch_error || rresp!=0 || rid!=0 || rlast!=(beat==3);
 if(beat==3)begin
 if(fetch_error || rresp!=0 || rid!=0 || !rlast || (rdata!=1 && MUTATION!=2))finish(1,0);
 else if(abort_pending || abort_req)finish(0,1);
 else begin state<=PROGRAM;program_index<=0;phase<=0;end
 end else beat<=beat+1'b1;
 end
 PROGRAM:begin
 if(program_index==3 && !phase && (abort_pending || abort_req))finish(0,1);
 else if(!phase)phase<=1;
 else if(pready)begin
 phase<=0;if(pslverr)finish(1,0);
 else if(program_index==3)begin state<=POLL;abort_sent<=0;end else program_index<=program_index+1'b1;
 end end
 POLL:begin
 if(!phase)begin wait_abort<=need_abort;phase<=1;end
 else if(pready)begin
 phase<=0;
 if(pslverr)finish(1,0);
 else if(wait_abort)abort_sent<=1;
 else if(prdata[1])begin
 if(prdata[2])finish(1,0);else if(prdata[3])finish(0,1);
 else begin
 completed<=completed+1'b1;
 if(abort_pending || abort_req)finish(0,1);
 else if(left==1)finish(0,0);
 else begin left<=left-1'b1;index<=(index+(MUTATION==1 ? 2:1))%DEPTH;state<=FETCH_AR;end
 end
 end
 end end
 default:;
 endcase
 end end
endmodule
