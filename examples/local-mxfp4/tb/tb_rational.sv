`timescale 1ns/1ps
// Expected bits are generated with Python fractions, independently of the SV oracle.
module tb_rational #(
  parameter bit GRADUAL_UF=0, USE_NEARFAR=0, SCALE34=0
);
  import mxfp4_pkg::*;
  logic clk;
  initial begin clk=0; forever #5 clk=~clk; end
  logic rst_n, in_valid, first, last, out_valid;
  logic [135:0] a_block, b_block;
  logic [31:0] result;
  logic enc_valid, enc_out_valid;
  logic [31:0] values [32];
  logic [135:0] encoded;
  mxfp4_bdp #(.GRADUAL_UF(GRADUAL_UF),.USE_NEARFAR(USE_NEARFAR)) bdp(
    .clk(clk),.rst_n(rst_n),.in_valid(in_valid),.in_ready(),.a_block(a_block),.b_block(b_block),
    .first(first),.last(last),.out_valid(out_valid),.out_ready(1'b1),.result(result),
    .sop4_dbg(),.sop_valid_dbg(),.exp_internal_dbg(),.exp_valid_dbg(),.gradual_uf_dbg());
  quant_encoder #(.UNBIASED_34(SCALE34)) encoder(
    .clk(clk),.rst_n(rst_n),.in_valid(enc_valid),.v_i(values),.blk_o(encoded),.out_valid(enc_out_valid),
    .e_rel_dbg(),.mag3_dbg(),.tie_hit_dbg(),.quant_valid_dbg());
  integer fd, n, op, f, l, cycle=0, checks=0, bdp_results=0, enc_results=0;
  logic [1023:0] data_a;
  logic [135:0] data_b, expected;
  logic [31:0] bdp_expected [integer];
  logic [135:0] enc_expected [integer];
  string vectors, wave;

  task automatic tick(input bit active);
    @(posedge clk); #1;
    if (out_valid !== bdp_expected.exists(cycle)) $fatal(1,"BDP_VALID cycle=%0d",cycle);
    if (out_valid) begin
      if (result !== bdp_expected[cycle]) $fatal(1,"BDP_DATA cycle=%0d got=%h expected=%h",cycle,result,bdp_expected[cycle]);
      bdp_expected.delete(cycle); bdp_results++;
    end
    if (enc_out_valid !== enc_expected.exists(cycle)) $fatal(1,"ENC_VALID cycle=%0d",cycle);
    if (enc_out_valid) begin
      if (encoded !== enc_expected[cycle]) $fatal(1,"ENC_DATA cycle=%0d got=%h expected=%h",cycle,encoded,enc_expected[cycle]);
      enc_expected.delete(cycle); enc_results++;
    end
    if (active) checks++;
    cycle++;
    @(negedge clk);
  endtask

  initial begin
    rst_n=0; in_valid=0; first=0; last=0; a_block=0; b_block=0; enc_valid=0;
    for(integer i=0;i<32;i++) values[i]=0;
    if (!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave)) $fatal(1,"arguments required");
    $dumpfile(wave); $dumpvars(1,tb_rational);
    fd=$fopen(vectors,"r"); if(!fd) $fatal(1,"vectors missing");
    repeat(2) @(negedge clk); rst_n=1;
    while (!$feof(fd)) begin
      n=$fscanf(fd,"%h %h %h %h %h %h\n",op,f,l,data_a,data_b,expected);
      if(n!=6) $fatal(1,"bad vector record");
      in_valid=(op==1); enc_valid=(op==2); first=1'(f); last=1'(l);
      a_block=data_a[135:0]; b_block=data_b;
      for(integer i=0;i<32;i++) values[i]=data_a[32*i +: 32];
      if(in_valid && last) bdp_expected[cycle+LAT-1]=expected[31:0];
      if(enc_valid) enc_expected[cycle+ENC_LAT-1]=expected;
      tick(1);
    end
    in_valid=0;enc_valid=0;
    repeat(LAT+1) tick(0);
    if(bdp_expected.num()!=0 || enc_expected.num()!=0) $fatal(1,"undrained expectations");
    $display("RATIONAL PASS checks=%0d bdp=%0d encoder=%0d",checks,bdp_results,enc_results);
    $finish;
  end
  initial begin #10_000_000; $fatal(1,"rational comparison timeout"); end
endmodule
