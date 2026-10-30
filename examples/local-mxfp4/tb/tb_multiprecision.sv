`timescale 1ns/1ps
module tb_multiprecision;
  import mp_pkg::*;
  logic clk,rst_n,in_valid,first,last,out_ready,in_ready,out_valid;
  logic [1:0] mode,golden_mode;
  logic [135:0] a_block,b_block;
  logic [31:0] result,legacy_result;
  logic err_scale_mismatch,err_protocol,legacy_valid;
  logic signed [41:0] sum8_dbg;
  logic sum8_valid_dbg;
  initial begin clk=0;forever #5 clk=~clk;end
  mp_bdp dut(.*);
  mxfp4_bdp legacy(.clk(clk),.rst_n(rst_n),.in_valid(in_valid && in_ready && golden_mode==FP4),
    .in_ready(),.a_block(a_block),.b_block(b_block),.first(first),.last(last),.out_valid(legacy_valid),
    .out_ready(out_ready),.result(legacy_result),.sop4_dbg(),.sop_valid_dbg(),.exp_internal_dbg(),.exp_valid_dbg(),.gradual_uf_dbg());
  integer fd,n,m,fv,lv,error_expected,gap,stall,check_sum,cycle=0,beats=0,results=0,sums=0,x0=0,held=0;
  logic [31:0] expected_bits,pending_bits;
  logic [41:0] sum_expected;
  logic [41:0] sum_queue [integer];
  integer due;
  bit pending=0;
  string vectors,wave;

  task automatic tick();
    bit consumed;
    consumed=out_valid && out_ready;
    @(posedge clk);#1;
    if(consumed) begin results++;pending=0;end
    if(out_valid !== (pending && cycle>=due)) $fatal(1,"MP_VALID cycle=%0d",cycle);
    if(out_valid) begin
      if(result!==pending_bits) $fatal(1,"MP_RESULT cycle=%0d got=%h expected=%h",cycle,result,pending_bits);
      if(!out_ready) held++;
    end
    if(golden_mode==FP4) begin
      if(out_valid!==legacy_valid) $fatal(1,"MP_X0_VALID");
      if(out_valid && result!==legacy_result) $fatal(1,"MP_X0_DATA");
      if(consumed) x0++;
    end
    if(sum_queue.exists(cycle)) begin
      if(!sum8_valid_dbg || sum8_dbg!==sum_queue[cycle]) $fatal(1,"MP_SUM42 cycle=%0d",cycle);
      sums++;sum_queue.delete(cycle);
    end
    cycle++;
    @(negedge clk);
  endtask

  initial begin
    rst_n=0;in_valid=0;first=0;last=0;out_ready=1;mode=FP4;golden_mode=FP4;a_block=0;b_block=0;
    if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave)) $fatal(1,"arguments required");
    $dumpfile(wave);$dumpvars(1,tb_multiprecision);
    fd=$fopen(vectors,"r");if(fd==0) $fatal(1,"vectors missing");
    repeat(2) @(negedge clk);rst_n=1;
    // Reserved mode is refused and diagnosed; a later valid first clears it.
    mode=3;in_valid=1;#1;if(in_ready) $fatal(1,"MP_RESERVED_READY");
    tick();if(!err_protocol) $fatal(1,"MP_RESERVED_DIAGNOSTIC");in_valid=0;
    while(!$feof(fd)) begin
      n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h\n",m,fv,lv,a_block,b_block,expected_bits,error_expected,gap,stall,sum_expected,check_sum);
      if(n!=11) $fatal(1,"bad MP row");
      in_valid=0;
      repeat(gap) tick();
      if(fv!=0) golden_mode=2'(m);
      mode=2'(m);first=1'(fv);last=1'(lv);in_valid=1;out_ready=!(lv!=0 && stall>0);
      #1;if(!in_ready) $fatal(1,"MP_UNEXPECTED_BACKPRESSURE");
      if(lv!=0) begin pending=1;pending_bits=expected_bits;due=cycle+(golden_mode==FP4 ? 5 : 7);end
      if(check_sum!=0) sum_queue[cycle+3]=sum_expected;
      tick();beats++;
      if({err_protocol,err_scale_mismatch}!==2'(error_expected)) $fatal(1,"MP_DIAGNOSTIC beat=%0d got=%b expected=%b",beats,{err_protocol,err_scale_mismatch},2'(error_expected));
      in_valid=0;
      if(lv!=0) begin
        while(!out_valid) tick();
        repeat(stall) tick();
        out_ready=1;tick();
        if(pending) $fatal(1,"MP_DRAIN");
      end
    end
    repeat(8) tick();
    if(sum_queue.num()!=0) $fatal(1,"MP_SUM42_INCOMPLETE");
    $display("MP PASS beats=%0d results=%0d sums=%0d x0=%0d held=%0d",beats,results,sums,x0,held);
    $finish;
  end
  initial begin #100_000_000;$fatal(1,"MP timeout");end
endmodule
