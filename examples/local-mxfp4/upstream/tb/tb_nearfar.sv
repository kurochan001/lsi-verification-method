// -----------------------------------------------------------------------------
// tb_nearfar
//   near/far 二経路 + LZA 版加算器 (mxfp4_fp32_add_nearfar) の検証。
//   仕様書 5.7 節の発展課題 / 11 章 段階 7。
//
//   完了基準は仕様書 12 章 注意 7 の「統合パス版とのビット一致回帰」。
//   統合パス版 (mxfp4_fp32_add_core) と near/far 版を FTZ / gradual の
//   両モードで並べ、r_sign / r_exp / r_sig / r_carry_ovf / r_zero の
//   全出力が一致することを確認する。
//
//   入力は内部表現 (sign, signed 11bit 指数, 暗黙 1 込み 24bit 仮数) で直接
//   与える。FP32 のビットパターン経由だと指数が 1..254 に限られ、
//   mxfp4_bdp が i2f 経由で作る負の内部指数や、デノーマルを正規化した
//   表現 (指数が負) を踏めないため。
//
//   LZA の予測誤差 (0 か 1) も毎回確認する。2 以上ずれると 1bit 補正では
//   足りず、pre-encoding の式が誤っていることになる。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_nearfar;

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  // ---------------------------------------------------------------------------
  // 共通入力
  // ---------------------------------------------------------------------------
  logic                     a_sign, b_sign;
  logic signed [IEXP_W-1:0] a_exp, b_exp;
  logic [SIGNIF_W-1:0]      a_sig, b_sig;

  // 統合パス (FTZ / gradual)
  logic                     sp_sign, sp_zero, sp_covf;
  logic signed [IEXP_W-1:0] sp_exp;
  logic [SIGNIF_W-1:0]      sp_sig;
  logic                     spg_sign, spg_zero, spg_covf;
  logic signed [IEXP_W-1:0] spg_exp;
  logic [SIGNIF_W-1:0]      spg_sig;

  // near/far (FTZ / gradual)
  logic                     nf_sign, nf_zero, nf_covf, nf_near;
  logic signed [IEXP_W-1:0] nf_exp;
  logic [SIGNIF_W-1:0]      nf_sig;
  logic [4:0]               nf_lza_err;
  logic                     nfg_sign, nfg_zero, nfg_covf, nfg_near;
  logic signed [IEXP_W-1:0] nfg_exp;
  logic [SIGNIF_W-1:0]      nfg_sig;
  logic [4:0]               nfg_lza_err;

  mxfp4_fp32_add_core #(.GRADUAL_UF(1'b0)) u_sp (
    .a_sign(a_sign), .a_exp(a_exp), .a_sig(a_sig),
    .b_sign(b_sign), .b_exp(b_exp), .b_sig(b_sig),
    .r_sign(sp_sign), .r_exp(sp_exp), .r_sig(sp_sig),
    .r_carry_ovf(sp_covf), .r_zero(sp_zero)
  );

  mxfp4_fp32_add_core #(.GRADUAL_UF(1'b1)) u_spg (
    .a_sign(a_sign), .a_exp(a_exp), .a_sig(a_sig),
    .b_sign(b_sign), .b_exp(b_exp), .b_sig(b_sig),
    .r_sign(spg_sign), .r_exp(spg_exp), .r_sig(spg_sig),
    .r_carry_ovf(spg_covf), .r_zero(spg_zero)
  );

  mxfp4_fp32_add_nearfar #(.GRADUAL_UF(1'b0)) u_nf (
    .a_sign(a_sign), .a_exp(a_exp), .a_sig(a_sig),
    .b_sign(b_sign), .b_exp(b_exp), .b_sig(b_sig),
    .r_sign(nf_sign), .r_exp(nf_exp), .r_sig(nf_sig),
    .r_carry_ovf(nf_covf), .r_zero(nf_zero),
    .near_dbg(nf_near), .lza_err_dbg(nf_lza_err)
  );

  mxfp4_fp32_add_nearfar #(.GRADUAL_UF(1'b1)) u_nfg (
    .a_sign(a_sign), .a_exp(a_exp), .a_sig(a_sig),
    .b_sign(b_sign), .b_exp(b_exp), .b_sig(b_sig),
    .r_sign(nfg_sign), .r_exp(nfg_exp), .r_sig(nfg_sig),
    .r_carry_ovf(nfg_covf), .r_zero(nfg_zero),
    .near_dbg(nfg_near), .lza_err_dbg(nfg_lza_err)
  );

  // ---------------------------------------------------------------------------
  // 集計
  // ---------------------------------------------------------------------------
  int checks;
  int errors;
  int n_near;          // near path を通った回数
  int n_far;
  int n_lza0, n_lza1;  // LZA 予測誤差の分布
  int n_cancel;        // 完全相殺
  int n_denorm;        // gradual 版がデノーマルを返した回数

  task automatic chk_pair(input string name);
    checks++;
    if ({sp_sign, sp_exp, sp_sig, sp_covf, sp_zero} !==
        {nf_sign, nf_exp, nf_sig, nf_covf, nf_zero}) begin
      errors++;
      if (errors <= 20)
        $display("[FAIL] %s ftz: a=%b/%0d/%h b=%b/%0d/%h\n  single=%b/%0d/%h ovf=%b z=%b\n  nearfar=%b/%0d/%h ovf=%b z=%b (near=%b)",
                 name, a_sign, a_exp, a_sig, b_sign, b_exp, b_sig,
                 sp_sign, sp_exp, sp_sig, sp_covf, sp_zero,
                 nf_sign, nf_exp, nf_sig, nf_covf, nf_zero, nf_near);
    end

    checks++;
    if ({spg_sign, spg_exp, spg_sig, spg_covf, spg_zero} !==
        {nfg_sign, nfg_exp, nfg_sig, nfg_covf, nfg_zero}) begin
      errors++;
      if (errors <= 20)
        $display("[FAIL] %s grd: a=%b/%0d/%h b=%b/%0d/%h\n  single=%b/%0d/%h ovf=%b z=%b\n  nearfar=%b/%0d/%h ovf=%b z=%b (near=%b)",
                 name, a_sign, a_exp, a_sig, b_sign, b_exp, b_sig,
                 spg_sign, spg_exp, spg_sig, spg_covf, spg_zero,
                 nfg_sign, nfg_exp, nfg_sig, nfg_covf, nfg_zero, nfg_near);
    end

    // LZA の予測誤差は 0 か 1 でなければならない (1bit 補正の前提)
    if (nf_near) begin
      n_near++;
      checks++;
      if (nf_lza_err > 5'd1) begin
        errors++;
        $display("[FAIL] %s: LZA misprediction by %0d bits", name, nf_lza_err);
      end
      if (nf_lza_err == 5'd0) n_lza0++;
      else                    n_lza1++;
    end else begin
      n_far++;
    end
    if (sp_zero) n_cancel++;
    if (!spg_zero && !spg_sig[SIGNIF_W-1]) n_denorm++;
  endtask

  task automatic drive(input logic sa, input logic signed [IEXP_W-1:0] ea,
                       input logic [SIGNIF_W-1:0] ma,
                       input logic sb, input logic signed [IEXP_W-1:0] eb,
                       input logic [SIGNIF_W-1:0] mb);
    a_sign = sa; a_exp = ea; a_sig = ma;
    b_sign = sb; b_exp = eb; b_sig = mb;
    #1;
  endtask

  // 正規化済み仮数 (bit23 = 1)
  function automatic logic [SIGNIF_W-1:0] rand_sig();
    return {1'b1, 23'($urandom)};
  endfunction

  // ---------------------------------------------------------------------------
  // シナリオ
  // ---------------------------------------------------------------------------
  // N1: near path 狙い。異符号 + 指数差 0/1。
  task automatic test_near(input int n_iter);
    logic signed [IEXP_W-1:0] e;
    logic s;
    $display("--- N1: near path (opposite signs, |exp diff| <= 1) ---");
    for (int t = 0; t < n_iter; t++) begin
      e = IEXP_W'($urandom_range(1, 254));
      s = 1'($urandom_range(0, 1));
      drive(s,  e,                    rand_sig(),
            ~s, e - IEXP_W'($urandom_range(0, 1)), rand_sig());
      chk_pair("N1");
    end
  endtask

  // N2: 大きなキャンセル。上位ビットを揃えて桁落ちを最大化する。
  task automatic test_cancel(input int n_iter);
    logic [SIGNIF_W-1:0] m, m2;
    logic signed [IEXP_W-1:0] e;
    int k;
    $display("--- N2: massive cancellation (LZA stress) ---");
    for (int t = 0; t < n_iter; t++) begin
      e = IEXP_W'($urandom_range(1, 254));
      m = rand_sig();
      // 上位 k bit を共有し、下位だけ変える -> 減算で k bit 桁落ち
      k = $urandom_range(0, 23);
      m2 = m;
      for (int i = 0; i < k; i++) m2[i] = 1'($urandom_range(0, 1));
      drive(1'b0, e, m, 1'b1, e, m2);
      chk_pair("N2 same-exp");
      // 指数差 1 側 (アライン 1bit 後に桁落ち)
      drive(1'b0, e, m, 1'b1, e - IEXP_W'(1), m2);
      chk_pair("N2 diff1");
    end
  endtask

  // N3: far path。同符号 / 指数差 >= 2。
  task automatic test_far(input int n_iter);
    logic signed [IEXP_W-1:0] e;
    int d;
    $display("--- N3: far path (same sign or |exp diff| >= 2) ---");
    for (int t = 0; t < n_iter; t++) begin
      e = IEXP_W'($urandom_range(1, 254));
      d = $urandom_range(2, 40);
      drive(1'b0, e, rand_sig(), 1'b0, e - IEXP_W'(d), rand_sig());
      chk_pair("N3 add");
      drive(1'b0, e, rand_sig(), 1'b1, e - IEXP_W'(d), rand_sig());
      chk_pair("N3 sub");
    end
  endtask

  // N4: 内部表現の全域。i2f 由来の負の指数やデノーマル正規化表現も含む。
  task automatic test_wide(input int n_iter);
    logic signed [IEXP_W-1:0] ea, eb;
    $display("--- N4: full internal exponent range (incl. negative) ---");
    for (int t = 0; t < n_iter; t++) begin
      ea = IEXP_W'($urandom_range(0, 400)) - IEXP_W'(140);
      eb = IEXP_W'($urandom_range(0, 400)) - IEXP_W'(140);
      drive(1'($urandom_range(0,1)), ea, rand_sig(),
            1'($urandom_range(0,1)), eb, rand_sig());
      chk_pair("N4");
    end
  endtask

  // N5: アンダーフロー域 (gradual 版でデノーマルが出る帯)
  task automatic test_underflow(input int n_iter);
    logic signed [IEXP_W-1:0] ea, eb;
    $display("--- N5: underflow band (denormal results) ---");
    for (int t = 0; t < n_iter; t++) begin
      ea = IEXP_W'($urandom_range(0, 30)) - IEXP_W'(24);
      eb = ea - IEXP_W'($urandom_range(0, 2));
      drive(1'($urandom_range(0,1)), ea, rand_sig(),
            1'($urandom_range(0,1)), eb, rand_sig());
      chk_pair("N5");
    end
  endtask

  // N6: 直接テスト (完全相殺 / 1ulp 差 / 桁上げ / 最大指数)
  task automatic test_direct();
    $display("--- N6: direct corner cases ---");
    // 完全相殺
    drive(1'b0, IEXP_W'(127), 24'h800000, 1'b1, IEXP_W'(127), 24'h800000);
    chk_pair("N6 cancel");
    // 1ulp 差 (最大の桁落ち)
    drive(1'b0, IEXP_W'(127), 24'h800001, 1'b1, IEXP_W'(127), 24'h800000);
    chk_pair("N6 1ulp");
    // 指数差 1 で 0.5ulp
    drive(1'b0, IEXP_W'(127), 24'h800000, 1'b1, IEXP_W'(126), 24'hFFFFFF);
    chk_pair("N6 half");
    // 桁上げする加算
    drive(1'b0, IEXP_W'(127), 24'hFFFFFF, 1'b0, IEXP_W'(127), 24'hFFFFFF);
    chk_pair("N6 carry");
    // 丸め桁上げ (仮数が全 1 で +1 されて 25bit へ)
    drive(1'b0, IEXP_W'(127), 24'hFFFFFF, 1'b0, IEXP_W'(100), 24'h800000);
    chk_pair("N6 round carry");
    // 指数の上端 / 下端
    drive(1'b0, IEXP_W'(254), 24'hFFFFFF, 1'b0, IEXP_W'(254), 24'hFFFFFF);
    chk_pair("N6 overflow");
    drive(1'b0, IEXP_W'(1), 24'hFFFFFF, 1'b1, IEXP_W'(1), 24'hFFFFFE);
    chk_pair("N6 min exp");
    drive(1'b0, -IEXP_W'(100), 24'hABCDEF, 1'b1, -IEXP_W'(101), 24'h912345);
    chk_pair("N6 negative exp");
  endtask

  int n_iter;

  initial begin
    if (!$value$plusargs("N_NF=%d", n_iter)) n_iter = 50000;

    checks   = 0;
    errors   = 0;
    n_near   = 0;
    n_far    = 0;
    n_lza0   = 0;
    n_lza1   = 0;
    n_cancel = 0;
    n_denorm = 0;

    a_sign = 1'b0; a_exp = '0; a_sig = '0;
    b_sign = 1'b0; b_exp = '0; b_sig = '0;
    #1;

    test_direct();
    test_near(n_iter);
    test_cancel(n_iter / 2);
    test_far(n_iter / 2);
    test_wide(n_iter);
    test_underflow(n_iter);

    // 非 vacuous: 両経路と LZA の補正が実際に踏まれていること
    checks++;
    if (n_near == 0) begin errors++; $display("[FAIL] near path never taken"); end
    checks++;
    if (n_far == 0)  begin errors++; $display("[FAIL] far path never taken");  end
    checks++;
    if (n_lza1 == 0) begin
      errors++;
      $display("[FAIL] LZA 1-bit correction never exercised");
    end

    $display("=====================================");
    $display(" tb_nearfar : %0d checks, %0d errors", checks, errors);
    $display("   near=%0d far=%0d  LZA exact=%0d corrected=%0d",
             n_near, n_far, n_lza0, n_lza1);
    $display("   full cancellation=%0d  denormal (gradual)=%0d", n_cancel, n_denorm);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

endmodule
