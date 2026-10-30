// -----------------------------------------------------------------------------
// tb_fp32_add
//   mxfp4_fp32_add_core を汎用 FP32 加算器として単体検証する。
//
//   BDP 経由の R2a/R2e では第 2 項が i2f 由来 (13bit 仮数、下位 11bit 以上が 0) に
//   限られるうえ、acc の仮数もブロック数が少ないと埋まりきらないため、
//   「実効加算 + 桁上げ + sticky != 0」が丸めに効く条件をほとんど踏めない。
//   ここでは両オペランドに任意の FP32 を与えてその穴を埋める。
//
//   仕様書 5.3 節 5. の「桁上げ時に押し出されるビットを sticky へ OR」が
//   実装されていないと、このテストだけが落ちる。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_fp32_add;

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  logic                     a_sign, b_sign, r_sign, r_zero, r_carry_ovf;
  logic signed [IEXP_W-1:0] a_exp, b_exp, r_exp;
  logic [SIGNIF_W-1:0]      a_sig, b_sig, r_sig;

  mxfp4_fp32_add_core dut (
    .a_sign(a_sign), .a_exp(a_exp), .a_sig(a_sig),
    .b_sign(b_sign), .b_exp(b_exp), .b_sig(b_sig),
    .r_sign(r_sign), .r_exp(r_exp), .r_sig(r_sig),
    .r_carry_ovf(r_carry_ovf), .r_zero(r_zero)
  );

  int checks = 0;
  int errors = 0;

  // 内部指数 -> FP32 格納形式 (mxfp4_bdp の pack_fp32 と同一の規約)
  function automatic logic [31:0] pack_fp32(
      input logic sign, input logic signed [IEXP_W-1:0] iexp, input logic [SIGNIF_W-1:0] sig);
    if (iexp >= $signed(IEXP_W'(255))) return {sign, 8'hFF, 23'd0};
    else if (iexp <= $signed(IEXP_W'(0))) return {sign, 31'd0};
    else return {sign, iexp[7:0], sig[22:0]};
  endfunction

  // FP32 ペアを加算器に与えて結果を取り出す (組合せなので #1 で確定)
  task automatic add_fp32(input logic [31:0] x, input logic [31:0] y, output logic [31:0] z);
    a_sign = x[31];  a_exp = $signed({3'b000, x[30:23]});  a_sig = {1'b1, x[22:0]};
    b_sign = y[31];  b_exp = $signed({3'b000, y[30:23]});  b_sig = {1'b1, y[22:0]};
    #1;
    z = r_zero ? 32'h0000_0000 : pack_fp32(r_sign, r_exp, r_sig);
  endtask

  task automatic chk(input string name, input logic [31:0] x, input logic [31:0] y,
                     input logic [31:0] got, input logic [31:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      if (errors <= 20)
        $display("[FAIL] %s : %h + %h -> got=%h exp=%h", name, x, y, got, exp);
    end
  endtask

  // 正規数のみ (指数 1..254)
  function automatic logic [31:0] rand_norm(input int emin, input int emax);
    logic [31:0] f;
    f[31]    = 1'($urandom_range(0, 1));
    f[30:23] = 8'($urandom_range(emin, emax));
    f[22:0]  = 23'($urandom);
    return f;
  endfunction

  int n_rand;

  initial begin
    logic [31:0] x, y, z;
    int emin, d;

    if (!$value$plusargs("N_ADD=%d", n_rand)) n_rand = 300000;

    a_sign = 1'b0; a_exp = '0; a_sig = '0;
    b_sign = 1'b0; b_exp = '0; b_sig = '0;
    #1;

    // --- 仕様書チームから提示された反例 (A1) ---
    // sticky を捨てると 0x418240A2、正しくは 0x418240A3 (1ulp 差)
    $display("--- A1: reported counterexample ---");
    add_fp32(32'h417C7180, 32'h3F00FC52, z);
    chk("A1 counterexample", 32'h417C7180, 32'h3F00FC52, z, 32'h418240A3);

    // --- 指数差を狙い撃ちしたランダム ---
    // 実効加算 + 桁上げ + sticky != 0 が丸めに効くのは指数差が中程度の帯
    $display("--- targeted: same sign, exponent distance 1..30 ---");
    for (d = 1; d <= 30; d++) begin
      for (int t = 0; t < 2000; t++) begin
        emin = $urandom_range(30, 200);
        x = rand_norm(emin, emin);
        y = rand_norm(emin - d, emin - d);
        y[31] = x[31];                    // 同符号 = 実効加算
        x[22:0] = 23'h7FFFFF - 23'($urandom_range(0, 255));  // 桁上げしやすい仮数
        add_fp32(x, y, z);
        chk($sformatf("targeted d=%0d", d), x, y, z, ref_fp32_add_fp32(x, y));
      end
    end

    // --- 一様ランダム ---
    $display("--- uniform random (%0d pairs) ---", n_rand);
    for (int t = 0; t < n_rand; t++) begin
      x = rand_norm(1, 254);
      y = rand_norm(1, 254);
      add_fp32(x, y, z);
      chk("uniform", x, y, z, ref_fp32_add_fp32(x, y));
    end

    // --- 指数が近いランダム (相殺・桁上げが起きやすい) ---
    $display("--- near-exponent random (%0d pairs) ---", n_rand);
    for (int t = 0; t < n_rand; t++) begin
      emin = $urandom_range(20, 230);
      x = rand_norm(emin, emin + 4);
      y = rand_norm(emin, emin + 4);
      add_fp32(x, y, z);
      chk("near", x, y, z, ref_fp32_add_fp32(x, y));
    end

    $display("=====================================");
    $display(" tb_fp32_add : %0d checks, %0d errors", checks, errors);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

endmodule
