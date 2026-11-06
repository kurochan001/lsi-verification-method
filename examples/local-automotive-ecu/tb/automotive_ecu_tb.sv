// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module automotive_ecu_tb;
 parameter DATA_ID=16'ha12f,WINDOW_MIN=3,WINDOW_MAX=9,FRESH_MAX=13,MUTATION=0;
 reg clk=0,rst_n=0,arm=0,disarm=0,ack=0,recover=0,permit=0,external_fault=0,service=0,in_valid=0;
 reg [47:0] in_frame=0;
 wire in_ready,enabled,faulted,pending,frame_ok,frame_reject,irq,applied,cancelled;
 wire [1:0] frame_code;wire [15:0] drive_command;wire [4:0] cause;
 automotive_ecu #(.DATA_ID(DATA_ID),.WINDOW_MIN(WINDOW_MIN),.WINDOW_MAX(WINDOW_MAX),.FRESH_MAX(FRESH_MAX),.MUTATION(MUTATION)) dut(.*);
 always #5 clk=~clk;
 reg [63:0] v[0:9],e[0:11];reg [31:0] obs[0:11];
 reg pre_ready,old_enabled,old_fault,old_pending,old_rst=0;integer wd_elapsed=0,fresh_elapsed=0,errors_since_apply=0;
 integer fd,ef,cf,rc,checks,rows=0,inputs=0,validated=0,rejects=0,applies=0,cancels=0,reset_cancels=0,resets=0,faults=0,recoveries=0,starts=0,disarms=0;
 string vectors,expected,wave;
 task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"row=%0d cause=%0d",rows,cause);end endtask
 initial begin
  if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("EXPECTED=%s",expected)||!$value$plusargs("WAVE=%s",wave)||!$value$plusargs("CHECKS=%d",checks))$fatal(1,"arguments required");
  fd=$fopen(vectors,"r");ef=$fopen(expected,"r");cf=$fopen("trace.csv","w");if(!fd||!ef||!cf)$fatal(1,"inputs missing");
  $fdisplay(cf,"cycle,reset_n,arm,disarm,ack,recover,permit,external_fault,service,input_valid,frame,input_ready,enabled,faulted,command,cause,irq,applied,cancelled,frame_ok,frame_reject,frame_code,pending");
  $dumpfile(wave);$dumpvars(0,automotive_ecu_tb);@(negedge clk);
  while(!$feof(fd))begin
   for(integer j=0;j<10;j=j+1)begin rc=$fscanf(fd,"%h\n",v[j]);if(rc!=1)$fatal(1,"bad input");end
   for(integer j=0;j<12;j=j+1)begin rc=$fscanf(ef,"%h\n",e[j]);if(rc!=1)$fatal(1,"bad expected");end
   for(integer j=0;j<9;j=j+1)if(v[j]>1)fail("ECU_INPUT");if(v[9]>=64'h1000000000000)fail("ECU_INPUT");
   old_enabled=enabled;old_fault=faulted;old_pending=pending;
   rst_n=v[0][0];arm=v[1][0];disarm=v[2][0];ack=v[3][0];recover=v[4][0];permit=v[5][0];external_fault=v[6][0];service=v[7][0];in_valid=v[8][0];in_frame=v[9][47:0];#1;
   pre_ready=in_ready;inputs=inputs+int'(in_valid&&in_ready);
   if(!rst_n&&old_pending)begin reset_cancels=reset_cancels+1;$display("COVER reset/pending");end
   if(old_rst&&!rst_n)resets=resets+1;old_rst=rst_n;
   @(posedge clk);#1;rows=rows+1;
   if(!enabled&&(drive_command!=0||applied))fail("ECU_CONTAIN");if(enabled&&faulted)fail("ECU_CONTAIN");
   obs[1]=32'(enabled);obs[2]=32'(faulted);obs[3]=32'(drive_command);obs[4]=32'(cause);obs[5]=32'(irq);obs[6]=32'(applied);obs[7]=32'(cancelled);obs[8]=32'(frame_ok);obs[9]=32'(frame_reject);obs[10]=32'(frame_code);obs[11]=32'(pending);
   for(integer j=1;j<12;j=j+1)if(64'(obs[j])!==e[j])begin
    $display("FIELD %0d actual=%h expected=%h",j,obs[j],e[j]);
    if(j==1||j==2||j==4)fail("ECU_FAULT");else if(j==3||j==6||j==7)fail("ECU_COMMAND");else if(j==5)fail("ECU_IRQ");else fail("ECU_FRAME");
   end
   if(64'(pre_ready)!==e[0])fail("ECU_READY");
   if(rst_n)begin
    validated=validated+int'(frame_ok);rejects=rejects+int'(frame_reject);applies=applies+int'(applied);cancels=cancels+int'(cancelled);
    if(!old_enabled&&enabled)begin starts=starts+1;$display("COVER state/arm");end
    if(old_enabled&&!enabled&&!faulted)begin disarms=disarms+1;$display("COVER state/disarm");end
    if(applied)begin $display("COVER command/applied");if(drive_command==0)$display("COVER command/zero");if(drive_command==1000)$display("COVER command/max");if(fresh_elapsed+1==FRESH_MAX)$display("COVER fresh/deadline-command");end
    if(frame_reject)begin $display("COVER frame/discard");errors_since_apply=errors_since_apply+1;end
    if(old_enabled&&enabled&&service)begin if(wd_elapsed+1==WINDOW_MIN)$display("COVER watchdog/min-service");if(wd_elapsed+1==WINDOW_MAX)$display("COVER watchdog/max-service");end
    if(!old_fault&&faulted)begin
     faults=faults+1;
     if(cause[0])$display("COVER fault/external");if(cause[0]&&!old_enabled)$display("COVER fault/external-off");if(cause[1])$display("COVER fault/early");if(cause[2])$display("COVER fault/late");if(cause[3])begin $display("COVER fault/stale");if(errors_since_apply>0)$display("COVER fresh/reject-no-refresh");end
     if(cause[4])$display("COVER fault/range");if((cause&(cause-5'd1))!=0)$display("COVER fault/multiple");
     if(old_pending&&cancelled)$display("COVER fault/cancel-pending");
     if(old_pending&&cause[0]&&!applied&&drive_command==0)$display("COVER fault/over-commit");
    end
    if(old_fault&&faulted&&ack&&!recover&&!irq&&cause!=0)$display("COVER irq/ack-hold");
    if(old_fault&&recover&&!permit&&faulted)$display("COVER recovery/deny");
    if(old_fault&&!faulted)begin recoveries=recoveries+1;if(recover&&permit&&arm&&!enabled)$display("COVER recovery/separate-arm");end
   end
   if(!rst_n||!old_enabled||!enabled)begin wd_elapsed=0;fresh_elapsed=0;errors_since_apply=0;end
   else begin wd_elapsed=service ? 0:wd_elapsed+1;fresh_elapsed=applied ? 0:fresh_elapsed+1;if(applied)errors_since_apply=0;end
   $fdisplay(cf,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%012h,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d",rows,rst_n,arm,disarm,ack,recover,permit,external_fault,service,in_valid,in_frame,pre_ready,enabled,faulted,drive_command,cause,irq,applied,cancelled,frame_ok,frame_reject,frame_code,pending);
   @(negedge clk);
  end
  if(!$feof(ef)||rows!=checks||pending||enabled||drive_command!=0||inputs!=validated+rejects||validated!=applies+cancels+reset_cancels)fail("ECU_COMPLETION");
  $display("COUNT rows=%0d",rows);$display("COUNT inputs=%0d",inputs);$display("COUNT validated=%0d",validated);$display("COUNT rejected=%0d",rejects);$display("COUNT applied=%0d",applies);$display("COUNT cancelled=%0d",cancels);$display("COUNT reset_cancels=%0d",reset_cancels);$display("COUNT resets=%0d",resets);$display("COUNT faults=%0d",faults);$display("COUNT recoveries=%0d",recoveries);$display("COUNT starts=%0d",starts);$display("COUNT disarms=%0d",disarms);
  $display("RESULT PASS checks=%0d",rows);$fclose(fd);$fclose(ef);$fclose(cf);$finish;
 end
endmodule
