`timescale 1ns/1ps
module width_tb;
 parameter MUTATION=0,WAIT_CYCLES=0;
 reg clk=0;always #5 clk=~clk;reg rst_n=0;
 reg s_awvalid=0,s_wvalid=0,s_arvalid=0,s_bready=0,s_rready=0;
 reg [7:0] s_awaddr=0,s_araddr=0,s_wstrb=0;reg [63:0] s_wdata=0;
 wire s_awready,s_wready,s_arready,s_bvalid,s_rvalid;wire [1:0] s_bresp,s_rresp;wire [63:0] s_rdata;
 wire m_awvalid,m_awready,m_wvalid,m_wready,m_bready,m_arvalid,m_arready,m_rready;
 wire [7:0] m_awaddr,m_araddr;wire [31:0] m_wdata;wire [3:0] m_wstrb;
 reg m_bvalid=0,m_rvalid=0;reg [1:0] m_bresp=0,m_rresp=0;reg [31:0] m_rdata=0;
 axi_width64to32 #(.MUTATION(MUTATION)) dut(.*);
 integer ticks=0,lo_delay=0,kind=0,addr=0,error_addr=255,expected_half=0,seen_sub=0,completed_sub=0,checks=0;
 reg lo_awfull=0,lo_wfull=0,lo_read_pending=0,lo_b_pending=0;reg [7:0] lo_addr;reg [31:0] lo_data;reg [3:0] lo_strb;
 reg [7:0] memory[0:63],expected_memory[0:63];reg [63:0] tx_data;reg [7:0] tx_strb;
 reg b_held=0,r_held=0;reg [1:0] held_b,held_r;reg [63:0] held_data;
 assign m_awready=rst_n && !lo_awfull && !m_bvalid && ticks%3!=0;
 assign m_wready=rst_n && !lo_wfull && !m_bvalid && ticks%4!=0;
 assign m_arready=rst_n && !lo_read_pending && !m_rvalid && ticks%3!=1;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"operation=%0d kind=%0d",checks,kind);end endtask
 task check_sub(input integer a,input integer wr,input [31:0] d,input [3:0] st);
 begin
 if(wr && tx_strb==0)fail("WIDTH_SUBSTRB");
 if(wr && seen_sub==0 && tx_strb[3:0]==0)expected_half=1;
 if(a!==addr+4*expected_half)fail("WIDTH_SUBADDR");
 if(wr)begin
 if(st!==(expected_half ? tx_strb[7:4]:tx_strb[3:0]))fail("WIDTH_SUBSTRB");
 if(d!==(expected_half ? tx_data[63:32]:tx_data[31:0]))fail("WIDTH_SUBDATA");
 end
 expected_half=expected_half+1;seen_sub=seen_sub+1;
 end endtask
 always @(posedge clk)begin
 ticks=ticks+1;
 if(!rst_n)begin lo_awfull<=0;lo_wfull<=0;m_bvalid<=0;m_rvalid<=0;lo_read_pending<=0;lo_b_pending<=0;lo_delay<=0;b_held<=0;r_held<=0;end
 else begin
 if(b_held && (!s_bvalid || s_bresp!==held_b))fail("WIDTH_HOLD");
 if(r_held && (!s_rvalid || {s_rresp,s_rdata}!=={held_r,held_data}))fail("WIDTH_HOLD");
 b_held<=s_bvalid&&!s_bready;held_b<=s_bresp;r_held<=s_rvalid&&!s_rready;held_r<=s_rresp;held_data<=s_rdata;
 if(s_bvalid&&!s_bready)$display("COVER response/write-stall");if(s_rvalid&&!s_rready)$display("COVER response/read-stall");
 if(m_awvalid && m_awready)begin lo_awfull<=1;lo_addr<=m_awaddr;end
 if(m_wvalid && m_wready)begin lo_wfull<=1;lo_data<=m_wdata;lo_strb<=m_wstrb;end
 if(lo_awfull && lo_wfull && !m_bvalid && !lo_b_pending)begin
 check_sub(lo_addr,1,lo_data,lo_strb);
 if(lo_addr!=error_addr)for(integer l=0;l<4;l=l+1)if(lo_strb[l])memory[lo_addr+l]<=lo_data[8*l+:8];
 m_bresp<=lo_addr==error_addr ? 2:0;lo_b_pending<=1;lo_delay<=WAIT_CYCLES;lo_awfull<=0;lo_wfull<=0;
 end
 if(lo_b_pending && !m_bvalid)begin
 if(lo_delay==0)begin m_bvalid<=1;lo_b_pending<=0;end else lo_delay<=lo_delay-1;
 end
 if(m_bvalid && m_bready)begin
 m_bvalid<=0;completed_sub=completed_sub+1;
 end
 if(m_arvalid && m_arready)begin
 check_sub(m_araddr,0,0,0);lo_read_pending<=1;lo_delay<=WAIT_CYCLES;
 m_rresp<=m_araddr==error_addr ? 2:0;
 m_rdata<=m_araddr==error_addr ? 0:{memory[m_araddr+3],memory[m_araddr+2],memory[m_araddr+1],memory[m_araddr]};
 end
 if(lo_read_pending && !m_rvalid)begin
 if(lo_delay==0)begin m_rvalid<=1;lo_read_pending<=0;end else lo_delay<=lo_delay-1;
 end
 if(m_rvalid && m_rready)begin m_rvalid<=0;completed_sub=completed_sub+1;end
 end
 end
 integer fd,n,cycles,aw_delay,w_delay,stall,b_seen,r_seen,expected_sub,aw_cycle,w_cycle,first_write_half,recovery_addr;
 reg recovering=0;reg [63:0] v[0:10];string vectors,wave;
 reg aw_sent,w_sent,ar_sent,finished,ah,wh,rh,bh,dh;
 task reset_bus;begin
 rst_n=0;s_awvalid=0;s_wvalid=0;s_arvalid=0;s_bready=0;s_rready=0;
 repeat(2)@(negedge clk);rst_n=1;@(negedge clk);
 if(s_bvalid || s_rvalid)fail("WIDTH_RESET");
 end endtask
 initial begin
 for(integer i=0;i<64;i=i+1)begin memory[i]=0;expected_memory[i]=0;end
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,width_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10]);if(n!=11)$fatal(1,"bad row");
 kind=v[0];addr=v[1];tx_data=v[2];tx_strb=v[3];aw_delay=v[4];w_delay=v[5];stall=v[6];error_addr=v[7];expected_sub=v[10];
 seen_sub=0;completed_sub=0;expected_half=0;
 if(kind==0)reset_bus();
 else begin
 first_write_half=tx_strb[3:0]==0 ? 1:0;
 if((kind==1 || kind==3) && addr%8==0)begin
 for(integer h=0;h<2;h=h+1)begin
 if(addr+h*4!=error_addr)for(integer l=0;l<4;l=l+1)if(tx_strb[h*4+l] && (kind!=3 || h==first_write_half))expected_memory[addr+h*4+l]=tx_data[8*(h*4+l)+:8];
 end end
 aw_sent=0;w_sent=0;ar_sent=0;aw_cycle=-1;w_cycle=-1;finished=0;b_seen=0;r_seen=0;cycles=0;
 while(!finished && cycles<300)begin
 s_awvalid=(kind==1 || kind==3) && !aw_sent && cycles>=aw_delay;s_awaddr=addr;
 s_wvalid=(kind==1 || kind==3) && !w_sent && cycles>=w_delay;s_wdata=tx_data;s_wstrb=tx_strb;
 s_arvalid=(kind==2 || kind==4) && !ar_sent;s_araddr=addr;
 s_bready=b_seen>=stall;s_rready=r_seen>=stall;
 #1;ah=s_awvalid&&s_awready;wh=s_wvalid&&s_wready;rh=s_arvalid&&s_arready;bh=s_bvalid&&s_bready;dh=s_rvalid&&s_rready;
 if((s_bvalid && kind!=1 && kind!=3) || (s_rvalid && kind!=2 && kind!=4))fail("WIDTH_CHANNEL");
 if(s_bvalid)b_seen=b_seen+1;if(s_rvalid)r_seen=r_seen+1;
 if((bh || dh) && kind>=3)fail("WIDTH_RESET");
 if(bh || dh)begin
 if((bh ? s_bresp:s_rresp)!==v[9][1:0])fail("WIDTH_RESPONSE");
 if(dh && s_rdata!==v[8])fail("WIDTH_READ");finished=1;
 end
 @(posedge clk);#1;if(ah)begin aw_sent=1;aw_cycle=cycles;end if(wh)begin w_sent=1;w_cycle=cycles;end if(rh)ar_sent=1;@(negedge clk);cycles=cycles+1;
 if(kind>=3 && completed_sub==1)begin reset_bus();recovering=1;recovery_addr=addr;$display("COVER reset/partial");finished=1;end
 end
 if(!finished)fail("WIDTH_TIMEOUT");
 s_awvalid=0;s_wvalid=0;s_arvalid=0;s_bready=0;s_rready=0;
 if(seen_sub!=expected_sub || completed_sub!=expected_sub)fail("WIDTH_SUBCOUNT");
 for(integer i=0;i<64;i=i+1)if(memory[i]!==expected_memory[i])fail("WIDTH_MEMORY");
 if(kind==1 || kind==3)begin
 if(tx_strb==0)$display("COVER strobe/zero");else if(tx_strb==255)$display("COVER strobe/full");else $display("COVER strobe/partial");
 if(tx_strb[3:0]==0 && tx_strb[7:4]!=0)$display("COVER strobe/upper-only");
 if(tx_strb[7:4]==0 && tx_strb[3:0]!=0)$display("COVER strobe/lower-only");
 if(aw_cycle>=0 && w_cycle>=0)begin
 if(aw_cycle>w_cycle)$display("COVER request/w-before-aw");if(aw_cycle<w_cycle)$display("COVER request/aw-before-w");end
 end else $display("COVER request/read");
 if(addr%8!=0)$display("COVER error/alignment");
 if(error_addr==addr)$display("COVER error/lower");if(error_addr==addr+4)$display("COVER error/upper");
 if(kind==2 && recovering && addr==recovery_addr)begin $display("COVER reset/recovery");recovering=0;end
 @(negedge clk);
 end
 checks=checks+1;
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
