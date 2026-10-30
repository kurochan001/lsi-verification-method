// -----------------------------------------------------------------------------
// tb_quant_q34
//   quant_encoder の 3/4 スケーリング unbiased 変形 (仕様書 7.7 節) の検証。
//   11 章 段階 7。
//
//   Algorithm 1 版 (UNBIASED_34 = 0) と 3/4 版 (UNBIASED_34 = 1) を並べて
//   同じブロックを投入し、次を確認する:
//     1. どちらもリファレンス (ref_encode_block_ex) とビット一致すること。
//        3/4 倍は RTL では 3m = m + 2m の 26bit 整数演算、リファレンスでは
//        real の 0.75 倍 + 7.2 節の区間表なので、経路は完全に独立している。
//     2. Algorithm 1 版がデフォルトのまま変わっていないこと
//        (仕様書 11 章 段階 7「導入時は統合パスとのビット一致回帰を必須とする」)。
//     3. 7.7 節の主張どおり、3/4 版では scaled 値が 6.0 (E2M1 の最大値) を
//        超える要素が構造的に消えること。Algorithm 1 では scaled amax が
//        [4, 8) に入るので amax の仮数が 1.5 以上のブロックで必ず起きる。
//
//   量子化誤差の偏りと RMS も測って表示する (PASS/FAIL の判定には使わない。
//   7.7 節が引く不偏性は stochastic rounding を前提とした主張であり、
//   本実装の roundTiesToEven では厳密な不偏にはならない)。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_quant_q34;

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  // ---------------------------------------------------------------------------
  // クロック
  // ---------------------------------------------------------------------------
  logic clk;

  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // ---------------------------------------------------------------------------
  // DUT (Algorithm 1 版と 3/4 版を同じ入力で並走させる)
  // ---------------------------------------------------------------------------
  logic               rst_n;
  logic               in_valid;
  logic [31:0]        v_i [K];
  logic [BLOCK_W-1:0] blk_a1, blk_34;
  logic               ov_a1, ov_34;

  logic signed [SCALED_EXP_W-1:0] erel_a1 [K], erel_34 [K];
  logic [2:0]                     mag_a1  [K], mag_34  [K];
  logic                           tie_a1  [K], tie_34  [K];
  logic                           qv_a1, qv_34;

  quant_encoder #(.UNBIASED_34(1'b0)) dut_a1 (
    .clk            (clk),
    .rst_n          (rst_n),
    .in_valid       (in_valid),
    .v_i            (v_i),
    .blk_o          (blk_a1),
    .out_valid      (ov_a1),
    .e_rel_dbg      (erel_a1),
    .mag3_dbg       (mag_a1),
    .tie_hit_dbg    (tie_a1),
    .quant_valid_dbg(qv_a1)
  );

  quant_encoder #(.UNBIASED_34(1'b1)) dut_34 (
    .clk            (clk),
    .rst_n          (rst_n),
    .in_valid       (in_valid),
    .v_i            (v_i),
    .blk_o          (blk_34),
    .out_valid      (ov_34),
    .e_rel_dbg      (erel_34),
    .mag3_dbg       (mag_34),
    .tie_hit_dbg    (tie_34),
    .quant_valid_dbg(qv_34)
  );

  // ---------------------------------------------------------------------------
  // 集計
  // ---------------------------------------------------------------------------
  int  checks;
  int  errors;
  int  n_elem;        // 量子化した要素の総数 (ゼロ要素を除く)
  int  n_over6_a1;    // Algorithm 1 で scaled > 6.0 だった要素数
  int  n_over6_34;    // 3/4 版で scaled > 6.0 だった要素数 (0 になるはず)
  real sum_abs;       // Σ|original|
  real sum_sq_orig;   // Σ original^2
  real sum_err_a1;    // Σ(decoded - original)              符号付きの偏り
  real sum_err_34;    // Σ((4/3) x decoded - original)
  real sum_mag_a1;    // Σ(|decoded| - |original|)          大きさの偏り
  real sum_mag_34;    // (クランプは大きさを縮める方向に効くのでこちらに出る)
  real sum_sq_a1;
  real sum_sq_34;

  task automatic chk_blk(input string name, input logic [BLOCK_W-1:0] got,
                         input logic [BLOCK_W-1:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      if (errors <= 20)
        $display("[FAIL] %s:\n   got=%h\n   exp=%h", name, got, exp);
    end
  endtask

  // ---------------------------------------------------------------------------
  // 投入 (仕様書 7.6 節のパイプライン段数を機械照合しながら流す)
  // ---------------------------------------------------------------------------
  task automatic run_both(input logic [31:0] v [K]);
    @(negedge clk);
    in_valid = 1'b1;
    for (int i = 0; i < K; i++) v_i[i] = v[i];
    @(negedge clk);
    in_valid = 1'b0;

    repeat (ENC_LAT - 2) @(posedge clk);
    #1;
    checks++;
    if (ov_a1 || ov_34) begin
      errors++;
      $display("[FAIL] out_valid earlier than ENC_LAT=%0d", ENC_LAT);
    end
    @(posedge clk);
    #1;
    checks++;
    if (!ov_a1 || !ov_34) begin
      errors++;
      $display("[FAIL] out_valid not asserted at ENC_LAT=%0d", ENC_LAT);
    end
  endtask

  // ---------------------------------------------------------------------------
  // 入力生成
  //   ブロック内の指数を狭い範囲に散らすと amax 近傍の要素が増え、
  //   Algorithm 1 のクランプ (scaled > 6.0) を踏みやすい。
  // ---------------------------------------------------------------------------
  function automatic logic [31:0] rand_fp32(input int e_lo, input int e_hi);
    logic [31:0] f;
    f[31]    = 1'($urandom_range(0, 1));
    f[30:23] = 8'($urandom_range(e_lo, e_hi));
    f[22:0]  = 23'($urandom);
    return f;
  endfunction

  // 量子化誤差とクランプの集計
  function automatic real fabs(input real x);
    return (x < 0.0) ? -x : x;
  endfunction

  task automatic accumulate(input logic [31:0] v [K]);
    real orig, scaled, dec_a1, dec_34;
    int  xb, ex;
    xb = int'(blk_a1[BLOCK_W-1 -: 8]);
    if (xb == 8'hFF) return;                    // NaN ブロックは対象外
    ex = 127 - xb;
    for (int i = 0; i < K; i++) begin
      if (v[i][30:23] == 8'h00) continue;       // DAZ 要素は対象外
      orig   = fp32_to_real(v[i]);
      scaled = fp32_to_real({1'b0, v[i][30:0]}) * (2.0 ** ex);
      dec_a1 = ref_decode_elem(blk_a1, i);
      dec_34 = ref_decode_elem(blk_34, i) * (4.0 / 3.0);

      n_elem++;
      if (scaled        > 6.0) n_over6_a1++;
      if (scaled * 0.75 > 6.0) n_over6_34++;

      sum_abs     += fabs(orig);
      sum_sq_orig += orig * orig;
      sum_err_a1  += dec_a1 - orig;
      sum_err_34  += dec_34 - orig;
      sum_mag_a1  += fabs(dec_a1) - fabs(orig);
      sum_mag_34  += fabs(dec_34) - fabs(orig);
      sum_sq_a1   += (dec_a1 - orig) * (dec_a1 - orig);
      sum_sq_34   += (dec_34 - orig) * (dec_34 - orig);
    end
  endtask

  // ---------------------------------------------------------------------------
  // シナリオ
  // ---------------------------------------------------------------------------
  task automatic test_random(input int n_iter);
    logic [31:0] v [K];
    int e_lo, e_hi;
    $display("--- Q1: random blocks, both modes vs reference (%0d blocks) ---", n_iter);
    for (int t = 0; t < n_iter; t++) begin
      e_lo = $urandom_range(20, 230);
      e_hi = e_lo + $urandom_range(0, 5);
      for (int i = 0; i < K; i++) v[i] = rand_fp32(e_lo, e_hi);
      run_both(v);
      chk_blk("Q1 alg1", blk_a1, ref_encode_block_ex(v, 1'b0));
      chk_blk("Q1 q34",  blk_34, ref_encode_block_ex(v, 1'b1));
      accumulate(v);
    end
  endtask

  // 3/4 倍の丸め境界を狙い撃つ。scaled が 7.2 節の中点に落ちる仮数を作る。
  task automatic test_boundary();
    logic [31:0] v [K];
    logic [23:0] m;
    $display("--- Q2: mantissa sweep around the 3/4 rounding boundaries ---");
    // 仮数全域を粗く掃きつつ、3m の桁上がり位置 (m = ceil(2^25/3)) の近傍を密に見る
    for (int base = 0; base < 24; base++) begin
      for (int d = -3; d <= 3; d++) begin
        for (int i = 0; i < K; i++) begin
          m = 24'(11184811 + d + (base * 555557));   // 2^25/3 近傍から等間隔に散らす
          v[i] = {1'b0, 8'd127, m[22:0]};
        end
        // ブロック内に大小を混ぜて amax を固定しつつ相対指数を散らす
        v[0]  = {1'b0, 8'd129, 23'h7FFFFF};
        v[1]  = {1'b1, 8'd128, 23'h000000};
        v[2]  = {1'b0, 8'd126, 23'h400000};
        run_both(v);
        chk_blk("Q2 alg1", blk_a1, ref_encode_block_ex(v, 1'b0));
        chk_blk("Q2 q34",  blk_34, ref_encode_block_ex(v, 1'b1));
        accumulate(v);
      end
    end
  endtask

  // エッジケース: 全ゼロ / NaN / デノーマル混在
  task automatic test_edge();
    logic [31:0] v [K];
    $display("--- Q3: edge cases (all zero / NaN / denormal) ---");

    for (int i = 0; i < K; i++) v[i] = 32'h0000_0000;
    run_both(v);
    chk_blk("Q3 allzero alg1", blk_a1, ref_encode_block_ex(v, 1'b0));
    chk_blk("Q3 allzero q34",  blk_34, ref_encode_block_ex(v, 1'b1));

    for (int i = 0; i < K; i++) v[i] = {1'b0, 8'd127, 23'h100000};
    v[7] = 32'h7FC0_0000;                      // qNaN
    run_both(v);
    chk_blk("Q3 nan alg1", blk_a1, ref_encode_block_ex(v, 1'b0));
    chk_blk("Q3 nan q34",  blk_34, ref_encode_block_ex(v, 1'b1));

    for (int i = 0; i < K; i++) v[i] = {1'b0, 8'd127, 23'h200000};
    v[3] = 32'h0000_0001;                      // デノーマル (DAZ)
    v[9] = 32'h8000_0000;                      // -0
    run_both(v);
    chk_blk("Q3 denorm alg1", blk_a1, ref_encode_block_ex(v, 1'b0));
    chk_blk("Q3 denorm q34",  blk_34, ref_encode_block_ex(v, 1'b1));
  endtask

  int n_iter;

  initial begin
    if (!$value$plusargs("N_Q34=%d", n_iter)) n_iter = 2000;

    checks     = 0;
    errors     = 0;
    n_elem     = 0;
    n_over6_a1 = 0;
    n_over6_34 = 0;
    sum_abs    = 0.0;
    sum_err_a1 = 0.0;
    sum_err_34 = 0.0;
    sum_sq_orig = 0.0;
    sum_mag_a1 = 0.0;
    sum_mag_34 = 0.0;
    sum_sq_a1  = 0.0;
    sum_sq_34  = 0.0;

    rst_n    = 1'b0;
    in_valid = 1'b0;
    for (int i = 0; i < K; i++) v_i[i] = '0;
    repeat (4) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    test_edge();
    test_boundary();
    test_random(n_iter);

    // 仕様書 7.7 節の主張: 3/4 版では 6.0 超え (クランプ) が構造的に消える
    checks++;
    if (n_over6_34 != 0) begin
      errors++;
      $display("[FAIL] 3/4 scaling still produced %0d element(s) above 6.0", n_over6_34);
    end
    // 非 vacuous: Algorithm 1 側では実際にクランプが起きていること
    checks++;
    if (n_over6_a1 == 0) begin
      errors++;
      $display("[FAIL] Algorithm 1 never clamped; comparison is meaningless");
    end

    $display("=====================================");
    $display(" tb_quant_q34 : %0d checks, %0d errors", checks, errors);
    $display("   elements=%0d", n_elem);
    $display("   above 6.0 (clamped): alg1=%0d (%.3f%%)  q34=%0d",
             n_over6_a1, 100.0 * real'(n_over6_a1) / real'(n_elem), n_over6_34);
    if (sum_abs > 0.0) begin
      // 符号付きの偏り。符号がキャンセルするのでクランプの影響は出にくい。
      $display("   signed bias    : alg1=%.5f  q34(x4/3)=%.5f",
               sum_err_a1 / sum_abs, sum_err_34 / sum_abs);
      // 大きさの偏り。クランプは |v| を 6.0 まで切り詰めるのでここに負で出る。
      $display("   magnitude bias : alg1=%.5f  q34(x4/3)=%.5f",
               sum_mag_a1 / sum_abs, sum_mag_34 / sum_abs);
      // 正規化 RMS 誤差 sqrt(Σerr^2 / Σorig^2)
      $display("   NRMSE          : alg1=%.5f  q34(x4/3)=%.5f",
               $sqrt(sum_sq_a1 / sum_sq_orig), $sqrt(sum_sq_34 / sum_sq_orig));
    end
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

endmodule
