// Teaching AXI4-Lite 64->32, one upstream operation, aligned 8-byte addresses.
// The two lower accesses are ordered and are not atomic. Errors do not roll back.
module axi_width64to32 #(parameter MUTATION=0)(
 input wire clk,rst_n,
 input wire s_awvalid,output wire s_awready,input wire [7:0] s_awaddr,
 input wire s_wvalid,output wire s_wready,input wire [63:0] s_wdata,input wire [7:0] s_wstrb,
 output reg s_bvalid,input wire s_bready,output reg [1:0] s_bresp,
 input wire s_arvalid,output wire s_arready,input wire [7:0] s_araddr,
 output reg s_rvalid,input wire s_rready,output reg [63:0] s_rdata,output reg [1:0] s_rresp,
 output wire m_awvalid,input wire m_awready,output wire [7:0] m_awaddr,
 output wire m_wvalid,input wire m_wready,output wire [31:0] m_wdata,output wire [3:0] m_wstrb,
 input wire m_bvalid,output wire m_bready,input wire [1:0] m_bresp,
 output wire m_arvalid,input wire m_arready,output wire [7:0] m_araddr,
 input wire m_rvalid,output wire m_rready,input wire [31:0] m_rdata,input wire [1:0] m_rresp
);
 localparam IDLE=0,WSEND=1,WRESP=2,RSEND=3,RRESP=4;
 reg [2:0] state;reg awfull,wfull,half,aw_sent,w_sent;reg [7:0] aw_buf,base,strb_buf;
 reg [63:0] data_buf,read_buf;reg [1:0] error_buf;
 wire idle=state==IDLE && !s_bvalid && !s_rvalid;
 assign s_awready=idle && !awfull;assign s_wready=idle && !wfull;
 assign s_arready=idle && !awfull && !wfull && !s_awvalid && !s_wvalid;
 assign m_awvalid=state==WSEND && !aw_sent;assign m_wvalid=state==WSEND && !w_sent;
 assign m_awaddr=base+(half ? 8'd4:8'd0);
 assign m_wdata=half ? data_buf[63:32]:data_buf[31:0];
 assign m_wstrb=half ? strb_buf[7:4]:strb_buf[3:0];
 assign m_bready=state==WRESP;assign m_arvalid=state==RSEND;
 assign m_araddr=base+(half ? 8'd4:8'd0);assign m_rready=state==RRESP;
 wire [1:0] werror=(error_buf!=0 || m_bresp!=0) ? 2'b10:2'b00;
 wire [1:0] rerror=(error_buf!=0 || m_rresp!=0) ? 2'b10:2'b00;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin
 state<=IDLE;awfull<=0;wfull<=0;aw_buf<=0;base<=0;strb_buf<=0;data_buf<=0;read_buf<=0;error_buf<=0;
 half<=0;aw_sent<=0;w_sent<=0;s_bvalid<=0;s_rvalid<=0;s_bresp<=0;s_rresp<=0;s_rdata<=0;
 end else begin
 if(s_bvalid && s_bready)s_bvalid<=0;if(s_rvalid && s_rready)s_rvalid<=0;
 if(s_awvalid && s_awready)begin aw_buf<=s_awaddr;awfull<=1;end
 if(s_wvalid && s_wready)begin data_buf<=MUTATION==1 ? {s_wdata[31:0],s_wdata[63:32]}:s_wdata;strb_buf<=MUTATION==2 ? 8'hff:s_wstrb;wfull<=1;end
 case(state)
 IDLE:begin
 if(idle && awfull && wfull)begin
 awfull<=0;wfull<=0;base<=aw_buf;error_buf<=0;aw_sent<=0;w_sent<=0;
 if(aw_buf[2:0]!=0)begin s_bvalid<=1;s_bresp<=2;end
 else if(strb_buf==0)begin s_bvalid<=1;s_bresp<=0;end
 else begin half<=strb_buf[3:0]==0;state<=WSEND;end
 end else if(s_arvalid && s_arready)begin
 base<=s_araddr;half<=0;read_buf<=0;error_buf<=0;
 if(s_araddr[2:0]!=0)begin s_rvalid<=1;s_rdata<=0;s_rresp<=2;end else state<=RSEND;
 end end
 WSEND:begin
 if(m_awvalid && m_awready)aw_sent<=1;if(m_wvalid && m_wready)w_sent<=1;
 if((aw_sent || m_awready) && (w_sent || m_wready))state<=WRESP;
 end
 WRESP:if(m_bvalid)begin
 error_buf<=werror;
 if(!half && strb_buf[7:4]!=0)begin half<=1;aw_sent<=0;w_sent<=0;state<=WSEND;end
 else begin s_bvalid<=1;s_bresp<=MUTATION==3 ? 0:werror;state<=IDLE;end
 end
 RSEND:if(m_arready)state<=RRESP;
 RRESP:if(m_rvalid)begin
 error_buf<=rerror;
 if(!half)begin read_buf[31:0]<=m_rdata;half<=1;state<=RSEND;end
 else begin s_rvalid<=1;s_rdata<={m_rdata,read_buf[31:0]};s_rresp<=MUTATION==3 ? 0:rerror;state<=IDLE;end
 end
 endcase
 if(MUTATION==4 && s_rvalid && !s_rready)s_rdata<=s_rdata^64'b1;
 end end
endmodule
