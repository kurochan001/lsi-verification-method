`timescale 1ns/1ps
module tb_mp_encoder;
  import mp_pkg::*;
  logic clk,rst_n,in_valid,out_ready,in_ready,out_valid,out_last,err_mode;
  logic [1:0] mode,out_mode;
  logic [1023:0] values;
  logic [135:0] block_data,legacy_block;
  logic legacy_valid;
  logic [31:0] legacy_values [32];
  initial begin clk=0;forever #5 clk=~clk;end
  mp_encoder dut(.*);
  for(genvar i=0;i<32;i++) begin: legacy_lanes
    assign legacy_values[i]=values[32*i +: 32];
  end
  quant_encoder legacy(.clk(clk),.rst_n(rst_n),.in_valid(in_valid && in_ready && mode==FP4),
    .v_i(legacy_values),.blk_o(legacy_block),.out_valid(legacy_valid),.e_rel_dbg(),.mag3_dbg(),.tie_hit_dbg(),.quant_valid_dbg());
  integer fd,n,m,count,stall,index=0,vectors_count=0,beats=0,x0=0,held=0;
  logic [543:0] expected;
  logic [135:0] old_block;
  logic [1:0] old_mode;
  logic old_last;
  bit legacy_pending=0;
  string vectors,wave;
  task automatic tick();
    bit consumed,was_held;
    consumed=out_valid && out_ready;was_held=out_valid && !out_ready;
    old_block=block_data;old_mode=out_mode;old_last=out_last;
    @(posedge clk);#1;
    if(consumed) begin beats++;index++;end
    if(was_held) begin
      held++;
      if(!out_valid || {block_data,out_mode,out_last}!=={old_block,old_mode,old_last}) $fatal(1,"MP_ENC_HOLD");
    end
    if(out_valid && (block_data!==expected[136*index +: 136] || out_mode!==2'(m) || out_last!==(index==count-1))) $fatal(1,"MP_ENC_DATA vector=%0d beat=%0d got=%h expected=%h",vectors_count,index,block_data,expected[136*index +: 136]);
    if(legacy_valid) begin
      if(!legacy_pending || legacy_block!==expected[135:0]) $fatal(1,"MP_ENC_X0");
      x0++;legacy_pending=0;
    end
    @(negedge clk);
  endtask
  initial begin
    rst_n=0;in_valid=0;out_ready=0;mode=FP4;values=0;
    if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave)) $fatal(1,"arguments required");
    $dumpfile(wave);$dumpvars(1,tb_mp_encoder);
    fd=$fopen(vectors,"r");if(fd==0) $fatal(1,"vectors missing");
    repeat(2) @(negedge clk);rst_n=1;
    // A reset discards an output burst, including its remaining three beats.
    mode=FP16;values={32{32'h3f800000}};in_valid=1;
    @(posedge clk);#1;if(!out_valid) $fatal(1,"MP_ENC_RESET_SETUP");
    @(negedge clk);in_valid=0;rst_n=0;#1;if(out_valid) $fatal(1,"MP_ENC_RESET");
    @(negedge clk);rst_n=1;
    mode=3;in_valid=1;#1;if(in_ready) $fatal(1,"MP_ENC_RESERVED_READY");
    @(posedge clk);#1;if(!err_mode) $fatal(1,"MP_ENC_RESERVED_ERROR");
    @(negedge clk);in_valid=0;
    while(!$feof(fd)) begin
      n=$fscanf(fd,"%h %h %h %h %h\n",m,values,count,expected,stall);
      if(n!=5) $fatal(1,"bad encoder row");
      mode=2'(m);index=0;in_valid=1;out_ready=0;legacy_pending=(m==2);
      #1;if(!in_ready) $fatal(1,"MP_ENC_READY");
      tick();in_valid=0;
      if(!out_valid) $fatal(1,"MP_ENC_LATENCY");
      if(err_mode) $fatal(1,"MP_ENC_ERROR");
      vectors_count++;
      for(integer i=0;i<count;i++) begin
        out_ready=0;mode=3; // The captured output mode must survive parked input controls.
        repeat(stall+(i%2)) tick();
        out_ready=1;tick();
      end
      if(out_valid || index!=count) $fatal(1,"MP_ENC_COMPLETION");
      while(legacy_pending) tick();
    end
    $display("MP_ENCODER PASS vectors=%0d beats=%0d x0=%0d held=%0d",vectors_count,beats,x0,held);
    $finish;
  end
  initial begin #100_000_000;$fatal(1,"MP encoder timeout");end
endmodule
