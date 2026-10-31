`timescale 1ns/1ps
module native_top #(parameter TRCD=2,TRP=2,TRAS=3,TWR=6,TRFC=5,CL=2,TREFI=24);
 dram_tb #(.TRCD(TRCD),.TRP(TRP),.TRAS(TRAS),.TWR(TWR),.TRFC(TRFC),.CL(CL),.TREFI(TREFI)) tb();
 bit disabled;
 covergroup commands with function sample(bit bank,bit [2:0] command);
  option.per_instance=1;
  bank_id:coverpoint bank {bins zero={0};bins one={1};}
  operation:coverpoint command {bins activate={1};bins read_data={2};bins write_data={3};bins precharge={4};}
  bank_command:cross bank_id,operation;
 endgroup
 covergroup refreshes with function sample(bit held);
  option.per_instance=1;
  response:coverpoint held {bins free={0};bins held={1};}
 endgroup
 covergroup responses with function sample(bit ready);
  option.per_instance=1;
  ready_state:coverpoint ready {bins held={0};bins accepted={1};}
 endgroup
 commands bank_cov=new();refreshes refresh_cov=new();responses output_cov=new();
 initial void'($value$plusargs("COVER_OFF=%d",disabled));
 always @(negedge tb.clk)begin
  #2;
  if(tb.rst_n && !disabled)begin
   if(tb.cmd>=1 && tb.cmd<=4)bank_cov.sample(tb.cmd_bank,tb.cmd);
   if(tb.cmd==5)refresh_cov.sample(tb.resp_valid && !tb.resp_ready);
   if(tb.resp_valid)output_cov.sample(tb.resp_ready);
  end
 end
endmodule
