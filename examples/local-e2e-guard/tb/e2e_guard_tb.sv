// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module e2e_guard_tb;
 parameter DATA_ID=16'ha12f,MUTATION=0;
 reg clk=0,rst_n=0,flush=0,in_valid=0,out_ready=0;
 reg [47:0] in_frame=0;
 wire in_ready,out_valid,accepted,rejected;wire [15:0] out_data;wire [1:0] reject_code;
 e2e_guard #(.DATA_ID(DATA_ID),.MUTATION(MUTATION)) dut(.*);
 always #5 clk=~clk;
 reg [63:0] v[0:4],e[0:5];reg [31:0] obs[0:5];
 reg pre_ready,old_valid,old_rst=0,seen=0,restart=1;reg [7:0] last_counter;reg [15:0] old_data;
 integer fd,ef,cf,rc,checks,rows=0,inputs=0,validated=0,rejects=0,retired=0,cancels=0,resets=0;
 string vectors,expected,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d",rows);end endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("EXPECTED=%s",expected)||!$value$plusargs("WAVE=%s",wave)||!$value$plusargs("CHECKS=%d",checks))$fatal(1,"arguments required");
  fd=$fopen(vectors,"r");ef=$fopen(expected,"r");cf=$fopen("trace.csv","w");if(!fd||!ef||!cf)$fatal(1,"inputs missing");
  $fdisplay(cf,"cycle,reset_n,flush,input_valid,input_ready,frame,output_ready,output_valid,output_data,accepted,rejected,reason");
  $dumpfile(wave);$dumpvars(0,e2e_guard_tb);@(negedge clk);
  while(!$feof(fd))begin
   for(integer j=0;j<5;j=j+1)begin rc=$fscanf(fd,"%h\n",v[j]);if(rc!=1)$fatal(1,"bad input");end
   for(integer j=0;j<6;j=j+1)begin rc=$fscanf(ef,"%h\n",e[j]);if(rc!=1)$fatal(1,"bad expected");end
   if(v[0]>1||v[1]>1||v[2]>1||v[3]>=64'h1000000000000||v[4]>1)fail("E2E_INPUT");
   old_valid=out_valid;old_data=out_data;
   rst_n=v[0][0];flush=v[1][0];in_valid=v[2][0];in_frame=v[3][47:0];out_ready=v[4][0];#1;
   pre_ready=in_ready;if(64'(pre_ready)!==e[0])fail("E2E_READY");
   if(in_valid&&!in_ready&&rst_n&&!flush)$display("COVER flow/input-stall");
   if(old_valid&&rst_n&&!flush&&!out_ready)$display("COVER flow/output-stall");
   if(old_valid&&(!rst_n||flush))begin cancels=cancels+1;if(!rst_n)$display("COVER reset/pending");else $display("COVER flush/pending");end
   if(old_valid&&rst_n&&!flush&&out_ready)retired=retired+1;
   if(old_rst&&!rst_n)resets=resets+1;old_rst=rst_n;
   inputs=inputs+int'(in_valid&&in_ready);
   @(posedge clk);#1;rows=rows+1;
   obs[0]=0;obs[1]=32'(out_valid);obs[2]=32'(out_data);obs[3]=32'(accepted);obs[4]=32'(rejected);obs[5]=32'(reject_code);
   if(old_valid&&rst_n&&!flush&&!out_ready&&(!out_valid||out_data!=old_data))fail("E2E_HOLD");
   for(integer j=3;j<6;j=j+1)if(64'(obs[j])!==e[j])fail("E2E_STATUS");
   for(integer j=1;j<3;j=j+1)if(64'(obs[j])!==e[j])begin
    $display("FIELD %0d actual=%h expected=%h",j,obs[j],e[j]);
    if(j==1)fail("E2E_STATE");else if(j==2)fail("E2E_DATA");else fail("E2E_STATUS");
   end
   if(!rst_n||flush)begin seen=0;restart=1;end
   if(accepted)begin
    validated=validated+1;$display("COVER frame/accepted");
    if(old_valid&&out_ready)$display("COVER flow/replace");
    if(in_frame[23:8]==0)$display("COVER payload/zero");if(in_frame[23:8]==16'hffff)$display("COVER payload/max");
    if(seen&&last_counter==255&&in_frame[31:24]==0)$display("COVER frame/wrap");
    if(restart&&in_frame[31:24]==0)begin $display("COVER reset/restart");restart=0;end
    seen=1;last_counter=in_frame[31:24];
   end
   if(rejected)begin
    rejects=rejects+1;
    case(reject_code)
     1:begin $display("COVER frame/crc-reject");if(in_frame[47:32]!=16'(DATA_ID))$display("COVER frame/error-priority");end
     2:$display("COVER frame/id-reject");
     3:begin $display("COVER frame/sequence-reject");if(seen&&in_frame[31:24]==last_counter)$display("COVER frame/repeat");else $display("COVER frame/gap");end
     default:fail("E2E_STATUS");
    endcase
   end
   $fdisplay(cf,"%0d,%0d,%0d,%0d,%0d,%012h,%0d,%0d,%0d,%0d,%0d,%0d",rows,rst_n,flush,in_valid,pre_ready,in_frame,out_ready,out_valid,out_data,accepted,rejected,reject_code);
   @(negedge clk);
  end
  if(!$feof(ef)||rows!=checks||out_valid||inputs!=validated+rejects||validated!=retired+cancels)fail("E2E_COMPLETION");
  $display("COUNT rows=%0d",rows);$display("COUNT inputs=%0d",inputs);$display("COUNT validated=%0d",validated);$display("COUNT rejected=%0d",rejects);$display("COUNT retired=%0d",retired);$display("COUNT cancelled=%0d",cancels);$display("COUNT resets=%0d",resets);
  $display("RESULT PASS checks=%0d",rows);$fclose(fd);$fclose(ef);$fclose(cf);$finish;
 end
endmodule
