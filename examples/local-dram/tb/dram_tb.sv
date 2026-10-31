`timescale 1ns/1ps
module dram_tb;
 parameter TRCD=2,TRP=2,TRAS=3,TWR=4,TRFC=5,CL=2,TREFI=24,MUTATION=0;
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,req_valid=0,req_write=0,req_bank=0,resp_ready=0,read_valid=0;
 reg [1:0] req_row=0,req_col=0;reg [31:0] req_data=0,read_data=0;
 wire req_ready,resp_valid;wire [31:0] resp_data,cmd_data;wire [2:0] cmd;wire cmd_bank;wire [1:0] cmd_row,cmd_col;
 dram_controller #(.TRCD(TRCD),.TRP(TRP),.TRAS(TRAS),.TWR(TWR),.TRFC(TRFC),.CL(CL),.TREFI(TREFI),.MUTATION(MUTATION)) dut(.*);
 integer fd,n,checks=0,b,i,quiet_until=0,refresh_origin=0,read_due=-1;
 integer opened[0:1],activated[0:1],written[0:1],precharged[0:1];
 reg [31:0] memory[0:31],read_value=0;reg pending=0;
 reg saved_bank=0,saved_write=0;reg [1:0] saved_row=0,saved_col=0;reg [31:0] saved_data=0;
 reg [63:0] v[0:11];string vectors,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
 initial begin
  for(b=0;b<2;b=b+1)begin opened[b]=-1;activated[b]=-1000;written[b]=-1000;precharged[b]=-1000;end
  for(i=0;i<32;i=i+1)memory[i]=0;
  if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
  $dumpfile(wave);$dumpvars(0,dram_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
  while(!$feof(fd))begin
   n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]);if(n!=12)$fatal(1,"bad row");
   rst_n=v[0][0];req_valid=v[1][0];req_write=v[2][0];req_bank=v[3][0];req_row=v[4][1:0];req_col=v[5][1:0];req_data=v[6][31:0];resp_ready=v[7][0];
   read_valid=rst_n && checks==read_due;read_data=read_value;#1;
   if(!rst_n)begin
    if(pending)$display("COVER reset/pending");pending=0;read_due=-1;quiet_until=0;refresh_origin=checks+1;
    for(b=0;b<2;b=b+1)begin opened[b]=-1;activated[b]=-1000;written[b]=-1000;precharged[b]=-1000;end
    for(i=0;i<32;i=i+1)memory[i]=0;
   end else begin
    // Observe actual command pins before checking the software scheduler's exact policy.
    b=int'(cmd_bank);
    if(cmd!=0 && checks<quiet_until)fail("DRAM_TIMING");
    case(cmd)
     1:begin
      if(opened[b]!=-1)fail("DRAM_STATE");if(checks-precharged[b]<TRP)fail("DRAM_TIMING");
      if(!pending || cmd_bank!==saved_bank || cmd_row!==saved_row)fail("DRAM_ADDRESS");
      opened[b]=int'(cmd_row);activated[b]=checks;$display("COVER command/activate");
      if(b==0)$display("COVER bank/zero");else $display("COVER bank/one");
     end
     2,3:begin
      if(opened[b]<0)fail("DRAM_STATE");if(checks-activated[b]<TRCD)fail("DRAM_TIMING");
      if(!pending || cmd_bank!==saved_bank || cmd_col!==saved_col || (cmd==3)!==saved_write || (cmd==3 && cmd_data!==saved_data))fail("DRAM_ADDRESS");
      i=b*16+opened[b]*4+int'(cmd_col);
      if(cmd==3)begin memory[i]=cmd_data;written[b]=checks;$display("COVER command/write");end
      else begin read_value=memory[i];read_due=checks+CL;$display("COVER command/read");end
     end
     4:begin
      if(opened[b]<0)fail("DRAM_STATE");
      if(checks-activated[b]<TRAS || checks-written[b]<TWR)fail("DRAM_TIMING");
      opened[b]=-1;precharged[b]=checks;$display("COVER command/precharge");
     end
     5:begin
      if(opened[0]>=0 || opened[1]>=0)fail("DRAM_STATE");
      if(checks-precharged[0]<TRP || checks-precharged[1]<TRP)fail("DRAM_TIMING");
      quiet_until=checks+TRFC;refresh_origin=checks+1;$display("COVER command/refresh");
      if(resp_valid && !resp_ready)$display("COVER refresh/held-response");
     end
     0:begin end
     default:fail("DRAM_COMMAND");
    endcase
    if(checks-refresh_origin>TREFI+TRAS+TWR+3*TRP+CL+8)fail("DRAM_REFRESH_BOUND");
    if(req_valid && req_ready)begin
     pending=1;saved_bank=req_bank;saved_row=req_row;saved_col=req_col;saved_write=req_write;saved_data=req_data;
     if(opened[int'(req_bank)]==int'(req_row))$display("COVER request/row-hit");
     else if(opened[int'(req_bank)]>=0)$display("COVER request/row-conflict");
    end
    if(dut.state==1 && cmd==0 && dut.opened[dut.saved_bank] && dut.row[dut.saved_bank]==dut.saved_row)$display("COVER timing/rcd-wait");
    if(dut.state==1 && cmd==0 && dut.opened[dut.saved_bank] && dut.row[dut.saved_bank]!=dut.saved_row)$display("COVER timing/precharge-wait");
    if(checks<quiet_until && cmd==0)$display("COVER timing/rfc-wait");
    if(dut.state==2 && !read_valid)$display("COVER read/latency");
    if(req_valid && !req_ready)$display("COVER request/backpressure");
    if(resp_valid)begin if(!resp_ready)$display("COVER response/hold");else begin pending=0;$display("COVER response/accepted");end end
   end
   if(req_ready!==v[8][0] || (rst_n && resp_valid!==v[9][0]))fail("DRAM_FLOW");
   if(rst_n && resp_valid && resp_data!==v[10][31:0])fail("DRAM_DATA");
   if(cmd!==v[11][2:0])fail("DRAM_POLICY");
   @(posedge clk);#1;checks=checks+1;@(negedge clk);
  end
  if(pending)fail("DRAM_UNDRAINED");
  $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
 end
endmodule
