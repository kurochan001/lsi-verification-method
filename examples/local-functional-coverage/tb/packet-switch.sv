`timescale 1ns/1ps
module native_top #(parameter WIDTH=8);
 packet_switch_tb #(.WIDTH(WIDTH)) tb();
 bit disabled;
 covergroup flits with function sample(bit output_port,bit last,bit ready);
  option.per_instance=1;
  port_id:coverpoint output_port {bins zero={0};bins one={1};}
  tail:coverpoint last {bins body={0};bins tail={1};}
  ready_state:coverpoint ready {bins held={0};bins accepted={1};}
  port_tail_ready:cross port_id,tail,ready_state;
 endgroup
 flits output_cov=new();
 initial void'($value$plusargs("COVER_OFF=%d",disabled));
 always @(negedge tb.clk)begin
  #2;
  if(tb.rst_n && !disabled)
   for(int o=0;o<2;o++)if(tb.m_valid[o])output_cov.sample(1'(o),tb.m_last[o],tb.m_ready[o]);
 end
endmodule
