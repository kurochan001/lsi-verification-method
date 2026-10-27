`timescale 1ns/1ps
module cache_tb;
 parameter MUTATION=0,LINES=2,LATENCY=1;reg clk=0;always #5 clk=~clk;
 reg rst_n=0;
reg req_valid=0;reg[3:0]req_strb=0;
reg [2:0] req_op=0;
reg [3:0] req_addr=0;
reg [31:0] req_data=0;
reg rsp_ready=0;
reg [3:0] debug_addr=0;
wire req_ready;
wire rsp_valid;
wire rsp_error;
wire [31:0] rsp_data;
wire [31:0] debug_data;
 integer fd,n,checks=0;reg [63:0] v[0:12];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d",checks);end endtask
 cache_dma #(.MUTATION(MUTATION),.LINES(LINES),.LATENCY(LATENCY)) dut(.*);reg recovering=0,active_stale=0;reg [2:0] active_op;reg [3:0] active_addr;
reg [31:0] clean_value[0:15];reg dirty_seen[0:15],dma_changed[0:15];
initial for(integer i=0;i<16;i=i+1)begin clean_value[i]=0;dirty_seen[i]=0;dma_changed[i]=0;end
 initial begin
 if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
 $dumpfile(wave);$dumpvars(0,cache_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");repeat(2)@(negedge clk);
 while(!$feof(fd))begin
 n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12]);if(n!=13)$fatal(1,"bad vector");
  if(!v[0] && rst_n && (dut.busy || rsp_valid))$display("COVER reset/pending");
 rst_n=v[0];
req_valid=v[1];
req_op=v[2];
req_addr=v[3];
req_data=v[4];
rsp_ready=v[5];
debug_addr=v[6];req_strb=v[7];
 #1;
 if(req_ready!==v[8][0:0])fail("CACHE_CONTROL");
if(rsp_valid!==v[9][0:0])fail("CACHE_CONTROL");
if(rsp_valid && rsp_error!==v[10][0:0])fail("CACHE_ERROR");
if(rsp_valid && rsp_data!==v[11][31:0])fail("CACHE_DATA");
if(debug_data!==v[12][31:0])fail("CACHE_MEMORY");

 if(!rst_n)begin recovering=1;for(integer i=0;i<16;i=i+1)begin dirty_seen[i]=0;dma_changed[i]=0;end end
 if(req_valid && req_ready)begin
 active_op=req_op;active_addr=req_addr;
 if((req_op==2 || req_op==6) && req_strb!=15 && req_strb!=0)$display("COVER strobe/partial");
 if((req_op==2 || req_op==6) && req_strb==0)$display("COVER strobe/zero");
 active_stale=dut.valid[req_addr%LINES] && dut.tag[req_addr%LINES]==req_addr && dut.data[req_addr%LINES]!=dut.memory[req_addr];
 case(req_op)
 1:$display("COVER cpu/read");2:begin $display("COVER cpu/write");dirty_seen[req_addr]=1;end
 3:begin $display("COVER maintenance/clean");dirty_seen[req_addr]=0;end
 4:$display("COVER maintenance/invalidate");5:$display("COVER dma/read");6:begin $display("COVER dma/write");dma_changed[req_addr]=1;end
 endcase
 if((req_op==1 || req_op==2) && dut.valid[req_addr%LINES] && dut.tag[req_addr%LINES]!=req_addr && dut.dirty[req_addr%LINES])$display("COVER cache/eviction");
 end
 if(rsp_valid && !rsp_ready)$display("COVER response/held");
 if(rsp_valid && rsp_ready)begin
 if(recovering)begin $display("COVER reset/recovery");recovering=0;end
 if(active_op==4 && rsp_error)$display("COVER maintenance/dirty-denied");
 if(active_op==5 && active_stale && dirty_seen[active_addr])$display("COVER visibility/stale-before-clean");
 if(active_op==1 && active_stale && dma_changed[active_addr])$display("COVER visibility/stale-before-invalidate");
 end

 @(posedge clk);#1;checks=checks+1;@(negedge clk);
 end
 $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
