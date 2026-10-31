`timescale 1ns/1ps
module native_top #(parameter ROUNDS=1);
 sha256_tb #(.ROUNDS(ROUNDS)) tb();
 bit disabled;
 covergroup lengths with function sample(bit [6:0] size);
  option.per_instance=1;
  length:coverpoint size {
   bins empty={0};bins short_message={[1:54]};bins end_one={55};bins start_two={56};
   bins partial={[57:63]};bins full_block={64};bins above_block={[65:118]};bins maximum={119};bins rejected={[120:127]};
  }
 endgroup
 covergroup responses with function sample(bit error,bit ready);
  option.per_instance=1;
  result:coverpoint error {bins okay={0};bins rejected={1};}
  ready_state:coverpoint ready {bins held={0};bins accepted={1};}
  result_ready:cross result,ready_state;
 endgroup
 lengths input_cov=new();responses output_cov=new();
 initial void'($value$plusargs("COVER_OFF=%d",disabled));
 // The vector driver settles at negedge+1; sample before the next acceptance edge.
 always @(negedge tb.clk)begin
  #2;
  if(tb.rst_n && !disabled)begin
   if(tb.cmd_valid && tb.cmd_ready)input_cov.sample(tb.length);
   if(tb.digest_valid)output_cov.sample(tb.error,tb.digest_ready);
  end
 end
endmodule
