// Either-side reset flushes both paths. Reset release is synchronized in each domain.
module cdc_apb_bridge #(parameter SYNC_STAGES=2,WAIT_CYCLES=0,MUTATION=0)(
 input wire sclk,pclk,srst_n,prst_n,req_valid,req_write,
 input wire [7:0] req_addr,input wire [31:0] req_data,input wire [15:0] req_tag,
 output wire req_ready,output reg rsp_valid,input wire rsp_ready,
 output reg rsp_error,output reg [31:0] rsp_data,output reg [15:0] rsp_tag,
 output wire source_up,target_up,
 output wire psel,penable,pwrite,output wire [7:0] paddr,output wire [31:0] pwdata,
 output wire pready,pslverr,output wire [31:0] prdata
);
 wire common_reset=srst_n && prst_n;
 (* ASYNC_REG="TRUE" *) reg [1:0] source_reset,target_reset;
 always @(posedge sclk or negedge common_reset)if(!common_reset)source_reset<=0;else source_reset<={source_reset[0],1'b1};
 always @(posedge pclk or negedge common_reset)if(!common_reset)target_reset<=0;else target_reset<={target_reset[0],1'b1};
 assign source_up=source_reset[1];assign target_up=target_reset[1];
 wire qfull,qempty,qvalid,rfull,rempty,rvalid;
 wire [56:0] qdata;wire [48:0] rdata;
 reg qfetch,rfetch;reg [56:0] active;reg [48:0] response;
 reg [1:0] state;reg response_pending;
 wire qread=target_up && !qfetch && state==0 && !response_pending && !qempty;
 wire rread=source_up && !rfetch && !rsp_valid && !rempty;
 assign req_ready=source_up && !qfull;
 packet_fifo #(.WIDTH(57),.SYNC_STAGES(SYNC_STAGES)) requests(
  .wclk(sclk),.rclk(pclk),.wrst_n(source_up),.rrst_n(target_up),.wr_en(req_valid&&req_ready),.rd_en(qread),
  .wr_data({req_write,req_addr,req_data,req_tag}),.full(qfull),.empty(qempty),.rd_valid(qvalid),.rd_data(qdata));
 packet_fifo #(.WIDTH(49),.SYNC_STAGES(SYNC_STAGES)) responses(
  .wclk(pclk),.rclk(sclk),.wrst_n(target_up),.rrst_n(source_up),.wr_en(response_pending&&!rfull),.rd_en(rread),
  .wr_data(response),.full(rfull),.empty(rempty),.rd_valid(rvalid),.rd_data(rdata));
 // Mutation 3 deliberately ignores a target-side reset for the source output slot.
 wire output_reset=MUTATION==3 ? srst_n:source_up;
 always @(posedge sclk or negedge output_reset)begin
  if(!output_reset)begin rfetch<=0;rsp_valid<=0;rsp_error<=0;rsp_data<=0;rsp_tag<=0;end
  else begin
   if(rread)rfetch<=1;
   if(rvalid)begin rfetch<=0;rsp_valid<=1;rsp_error<=MUTATION==4 ? 0:rdata[48];rsp_data<=rdata[47:16];rsp_tag<=rdata[15:0] ^ (MUTATION==1 ? 16'b1:0);end
   if(rsp_valid && rsp_ready)rsp_valid<=0;
  end
 end
 assign psel=state!=0;assign penable=state==2;assign pwrite=active[56];assign paddr=active[55:48] ^ (MUTATION==2 ? 8'd4:0);assign pwdata=active[47:16];
 always @(posedge pclk or negedge target_up)begin
  if(!target_up)begin qfetch<=0;state<=0;response_pending<=0;active<=0;response<=0;end
  else begin
   if(qread)qfetch<=1;
   if(qvalid)begin qfetch<=0;active<=qdata;state<=1;end
   if(state==1)state<=2;
   if(state==2 && pready)begin response<={pslverr,pwrite ? 32'b0:prdata,active[15:0]};response_pending<=1;state<=0;end
   if(response_pending && !rfull)response_pending<=0;
  end
 end
 wire [31:0] config_value;wire [3:0] pending;
 apb_regs #(.WAIT_CYCLES(WAIT_CYCLES)) registers(pclk,target_up,psel,penable,pwrite,paddr,pwdata,4'b0000,pready,pslverr,prdata,config_value,pending);
endmodule
