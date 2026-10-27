`timescale 1ns/1ps
module cdc_bridge_tb;
 parameter SRC_HALF=3,DST_HALF=7,SYNC_STAGES=2,WAIT_CYCLES=0,MUTATION=0;
 reg sclk=0,pclk=0;always #(SRC_HALF)sclk=~sclk;initial begin #2;forever #(DST_HALF)pclk=~pclk;end
 reg srst_n=0,prst_n=0,req_valid=0,req_write=0,rsp_ready=0;
 reg [7:0] req_addr=0;reg [31:0] req_data=0;reg [15:0] req_tag=0;
 wire req_ready,rsp_valid,rsp_error,source_up,target_up,psel,penable,pwrite,pready,pslverr;wire [7:0] paddr;wire [31:0] pwdata,prdata,rsp_data;wire [15:0] rsp_tag;
 cdc_apb_bridge #(.SYNC_STAGES(SYNC_STAGES),.WAIT_CYCLES(WAIT_CYCLES),.MUTATION(MUTATION)) dut(.*);
 integer fd,n,v[0:5],checks=0,requests=0,responses=0,apb=0,errors=0,flushes=0;
 integer qw=0,qr=0,ew=0,er=0,received=0;reg [31:0] config_model=0,checksum=0;
 reg [56:0] queue[0:20000];reg [48:0] expected[0:20000];reg [31:0] read_value;reg expected_error;
 reg held=0;reg [48:0] old_response;string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"batch=%0d",checks);end endtask
 always @(posedge sclk)if(source_up)begin
  if(req_valid && req_ready)begin queue[qw]={req_write,req_addr,req_data,req_tag};qw=qw+1;requests=requests+1;end
  if(held && (!rsp_valid || {rsp_error,rsp_data,rsp_tag}!==old_response))fail("CDC_DATA");
  held=rsp_valid&&!rsp_ready;old_response={rsp_error,rsp_data,rsp_tag};
  if(rsp_valid && rsp_ready)begin
   if(er>=ew || rsp_tag!==expected[er][15:0])fail("CDC_TAG");
   if({rsp_error,rsp_data}!==expected[er][48:16])fail("CDC_DATA");
   er=er+1;received=received+1;responses=responses+1;if(rsp_error)errors=errors+1;
   checksum=(checksum*33)^rsp_data^rsp_error^rsp_tag;
  end
 end
 always @(posedge pclk)if(target_up && psel && penable && pready)begin
  if(qr>=qw || {pwrite,paddr,pwdata}!==queue[qr][56:16])fail("CDC_APB");
  read_value=paddr==0 ? config_model:paddr==4 ? 32'h41504233:0;
  expected_error=(paddr!=0 && paddr!=4 && paddr!=8) || (pwrite && paddr==4);
  if(pslverr!==expected_error || (!pwrite && prdata!==read_value))fail("CDC_APB");
  expected[ew]={expected_error,pwrite ? 32'b0:read_value,queue[qr][15:0]};ew=ew+1;qr=qr+1;apb=apb+1;
  if(pwrite && !expected_error && paddr==0)config_model=pwdata;
  $display("COVER apb/transfer");if(expected_error)$display("COVER apb/error");
 end
 task wait_up;
  integer guard;begin guard=0;while(!source_up || !target_up)begin @(negedge sclk);guard=guard+1;if(guard>100)fail("CDC_RESET");end end
 endtask
 task pulse_reset(input integer which);
  begin
   req_valid=0;rsp_ready=0;
   if(which==1 || which==3)srst_n=0;if(which==2 || which==3)prst_n=0;
   #1;if(rsp_valid || req_ready)fail("CDC_RESET");
   #(4*(SRC_HALF+DST_HALF));
   qw=0;qr=0;ew=0;er=0;received=0;config_model=0;checksum=0;held=0;
   srst_n=1;prst_n=1;wait_up();
   repeat(3)@(negedge sclk);if(rsp_valid)fail("CDC_RESET");
  end
 endtask
 task automatic send(input integer index,input integer seed,input integer prefix);
  integer op,guard;begin
   op=prefix ? 0:index%5;req_write=op==0 || op==3;req_addr=op==0 || op==1 ? 0:op==2 || op==3 ? 4:12;
   req_data=seed+32'h01030507*index;req_tag=prefix ? 16'h8000:index+1;req_valid=1;guard=0;
   begin: accept forever begin @(posedge sclk);
    if(req_ready)begin #1;@(negedge sclk);disable accept;end
    #1;@(negedge sclk);guard=guard+1;if(guard>1000)fail("CDC_COUNT");
   end end
   req_valid=0;
  end
 endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,cdc_bridge_tb);@(negedge sclk);pulse_reset(3);
  fd=$fopen(vectors,"r");if(!fd)$fatal(1,"input missing");
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5]);if(n!=6)$fatal(1,"bad row");
   pulse_reset(3);
   if(v[2])begin
    send(0,v[1],1);
    begin: held_reply for(integer guard=0;guard<1000;guard=guard+1)begin
     @(negedge sclk);if(rsp_valid)disable held_reply;
    end fail("CDC_COUNT");end
    pulse_reset(v[2]);flushes=flushes+1;$display("COVER reset/side%0d",v[2]);
   end
   // Producer and receiver run concurrently; stalls pressure both asynchronous FIFOs.
   fork
    begin for(integer i=0;i<v[0];i=i+1)begin send(i,v[1],0);if(i%3==0)@(negedge sclk);end end
    begin
     for(integer guard=0;guard<20000 && received<v[0];guard=guard+1)begin
      rsp_ready=(guard%(v[3]+2))==v[3]+1;@(negedge sclk);
     end
     rsp_ready=0;if(received!=v[0])fail("CDC_COUNT");
    end
   join
   if(checksum!==v[4][31:0])fail("CDC_DATA");
   if(qw!=qr || ew!=er)fail("CDC_COUNT");
   $display("COVER transport/ordered");if(v[3])$display("COVER response/backpressure");
   checks=checks+1;
  end
  $display("COUNT requests=%0d",requests);$display("COUNT responses=%0d",responses);$display("COUNT apb=%0d",apb);$display("COUNT errors=%0d",errors);$display("COUNT flushes=%0d",flushes);
  $display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
