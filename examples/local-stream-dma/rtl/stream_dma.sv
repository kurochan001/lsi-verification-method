module stream_dma #(parameter MUTATION=0)(
 input wire clk,rst_n,start,direction,input wire[12:0]address,input wire[5:0]byte_count,output wire busy,irq,output reg done,error,
 output wire arvalid,input wire arready,output wire[12:0]araddr,output wire[7:0]arlen,output wire[1:0]arid,
 input wire rvalid,output wire rready,input wire[31:0]rdata,input wire[1:0]rid,rresp,input wire rlast,
 output wire awvalid,input wire awready,output wire[12:0]awaddr,output wire[7:0]awlen,output wire[1:0]awid,
 output wire wvalid,input wire wready,output wire[31:0]wdata,output wire[3:0]wstrb,output wire wlast,input wire bvalid,output wire bready,input wire[1:0]bid,bresp,
 output wire m_valid,input wire m_ready,output wire[31:0]m_data,output wire[3:0]m_keep,output wire m_last,
 input wire s_valid,output wire s_ready,input wire[31:0]s_data,input wire[3:0]s_keep,input wire s_last
);
 localparam IDLE=0,AR=1,READ=2,OUT=3,IN=4,WRITE=5,RESP=6;
 reg[2:0]state;reg[12:0]addr;reg[5:0]left;reg[31:0]buffer_data;reg[3:0]buffer_keep;reg aw_sent,w_sent;
 wire[3:0]mask=left>=4 ? 4'hf:(4'b0001<<left)-1;
 assign busy=state!=IDLE;assign irq=done;assign arvalid=rst_n && state==AR;assign araddr=addr;assign arlen=0;assign arid=1;assign rready=rst_n && state==READ;
 assign m_valid=rst_n && state==OUT;assign m_data=buffer_data^(MUTATION==4 ? 32'd1:0);assign m_keep=MUTATION==1 ? 4'hf:mask;assign m_last=(left<=4)^(MUTATION==2);assign s_ready=rst_n && state==IN;
 assign awvalid=rst_n && state==WRITE && !aw_sent;assign awaddr=addr;assign awlen=0;assign awid=2;assign wvalid=rst_n && state==WRITE && !w_sent;assign wdata=buffer_data;assign wstrb=MUTATION==3 ? 4'hf:buffer_keep;assign wlast=1;assign bready=rst_n && state==RESP;
 task finish(input bad);begin state<=IDLE;done<=1;error<=bad;end endtask
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin state<=IDLE;addr<=0;left<=0;buffer_data<=0;buffer_keep<=0;aw_sent<=0;w_sent<=0;done<=0;error<=0;end
 else case(state)
 IDLE:if(start)begin
 done<=0;error<=0;addr<=address;left<=byte_count;
 if(address[1:0]!=0 || byte_count>32 || ({1'b0,address}+((int'(byte_count)+3)/4)*4)>8192)finish(1);
 else if(byte_count==0)finish(0);else state<=direction ? IN:AR;
 end
 AR:if(arready)state<=READ;
 READ:if(rvalid)begin if(rresp!=0 || rid!=1 || !rlast)finish(1);else begin buffer_data<=rdata;state<=OUT;end end
 OUT:if(m_ready)begin if(left<=4)finish(0);else begin left<=left-4;addr<=addr+4;state<=AR;end end
 IN:if(s_valid)begin
 if(s_keep!=mask || s_last!=(left<=4))finish(1);
 else begin buffer_data<=s_data;buffer_keep<=s_keep;aw_sent<=0;w_sent<=0;state<=WRITE;end end
 WRITE:begin
 if(awvalid && awready)aw_sent<=1;if(wvalid && wready)w_sent<=1;
 if((aw_sent || (awvalid && awready)) && (w_sent || (wvalid && wready)))state<=RESP;
 end
 RESP:if(bvalid)begin if(bresp!=0 || bid!=2)finish(1);else if(left<=4)finish(0);else begin left<=left-4;addr<=addr+4;state<=IN;end end
 default:state<=IDLE;endcase
 end endmodule
