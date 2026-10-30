// -----------------------------------------------------------------------------
// tb_quant_encoder
//   量子化エンコーダのテストベンチ。仕様書 9.3 節のシナリオ D5 / R3。
//
//   D5 は e2m1_quantize を単体でインスタンス化して e_rel x 代表 frac を網羅する。
//   エンコーダ経由では e_rel が構造的に 2 以下に制限されるため (下記参照)、
//   丸め表の全数照合は単体テストでしか行えない。
//
//   [到達不能領域の明示 — 仕様書 9.4 節 cg_enc の bins hi = {[3:10]}]
//     e_rel = exp_field(Vi) - X_biased、X_biased = max(0, amax_exp - 2)、
//     かつ exp_field(Vi) <= amax_exp なので、
//       amax_exp >  2 のとき e_rel <= amax_exp - (amax_exp - 2) = 2
//       amax_exp <= 2 のとき e_rel <= amax_exp <= 2
//     すなわち quant_encoder の中では e_rel >= 3 は決して発生しない。
//     cg_enc の bins hi は除外 bin として扱うこと。
//     e2m1_quantize 単体では e_rel を直接与えられるので default 分岐も検査する。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_quant_encoder;

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  logic clk;
  logic rst_n;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // ---------------------------------------------------------------------------
  // DUT: quant_encoder
  // ---------------------------------------------------------------------------
  logic                           in_valid, out_valid;
  logic [31:0]                    v_i [K];
  logic [BLOCK_W-1:0]             blk_o;
  logic signed [SCALED_EXP_W-1:0] e_rel_dbg [K];
  logic [2:0]                     mag3_dbg  [K];
  logic                           tie_hit_dbg [K];
  logic                           quant_valid_dbg;

  quant_encoder dut (
    .clk      (clk),
    .rst_n    (rst_n),
    .in_valid (in_valid),
    .v_i      (v_i),
    .blk_o    (blk_o),
    .out_valid(out_valid),
    .e_rel_dbg      (e_rel_dbg),
    .mag3_dbg       (mag3_dbg),
    .tie_hit_dbg    (tie_hit_dbg),
    .quant_valid_dbg(quant_valid_dbg)
  );

  // ---------------------------------------------------------------------------
  // D5 用: e2m1_quantize 単体
  // ---------------------------------------------------------------------------
  logic signed [SCALED_EXP_W-1:0] q_erel;
  logic [22:0]                    q_frac;
  logic                           q_zero;
  logic [2:0]                     q_mag3;

  e2m1_quantize u_q (
    .e_rel_i  (q_erel),
    .frac_i   (q_frac),
    .is_zero_i(q_zero),
    .mag3_o   (q_mag3)
  );

  // ---------------------------------------------------------------------------
  // スコアボード
  // ---------------------------------------------------------------------------
  int checks = 0;
  int errors = 0;

  task automatic chk(input string name, input logic [135:0] got, input logic [135:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      $display("[FAIL] %s\n        got scale=%h elems=%h\n        exp scale=%h elems=%h",
               name, got[135:128], got[127:0], exp[135:128], exp[127:0]);
    end
  endtask

  task automatic chk3(input string name, input logic [2:0] got, input logic [2:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      $display("[FAIL] %s : got=%b exp=%b", name, got, exp);
    end
  endtask

  // stage5 で採取したタイ点命中フラグ
  logic tie_obs [K];

  // ---------------------------------------------------------------------------
  // 駆動タスク
  // ---------------------------------------------------------------------------
  task automatic run_enc(input logic [31:0] v [K], output logic [135:0] blk);
    @(negedge clk);
    in_valid = 1'b1;
    for (int i = 0; i < K; i++) v_i[i] = v[i];
    @(negedge clk);
    in_valid = 1'b0;

    // in_valid をサンプルする posedge は消化済み。残り ENC_LAT-1 個で out_valid。
    repeat (ENC_LAT - 2) @(posedge clk);
    #1;
    checks++;
    if (out_valid) begin
      errors++;
      $display("[FAIL] enc out_valid earlier than ENC_LAT=%0d", ENC_LAT);
    end
    // この時点が stage5 の組合せが有効なサイクル (仕様書 7.6 節 quant_valid_dbg)
    checks++;
    if (!quant_valid_dbg) begin
      errors++;
      $display("[FAIL] quant_valid_dbg not asserted at stage5");
    end
    for (int i = 0; i < K; i++) tie_obs[i] = tie_hit_dbg[i];
    @(posedge clk);
    #1;
    checks++;
    if (!out_valid) begin
      errors++;
      $display("[FAIL] enc out_valid not asserted at ENC_LAT=%0d", ENC_LAT);
    end
    blk = blk_o;
  endtask

  // ---------------------------------------------------------------------------
  // FP32 生成ヘルパー (仕様書 12 章 注意 6: 中点はビットパターンで直接与える)
  // ---------------------------------------------------------------------------
  function automatic logic [31:0] fp32(input logic s, input int exp_f, input logic [22:0] frac);
    return {s, 8'(exp_f), frac};
  endfunction

  function automatic logic [31:0] rand_fp32(input int emin, input int emax);
    logic [31:0] f;
    f[31]    = 1'($urandom_range(0, 1));
    f[30:23] = 8'($urandom_range(emin, emax));
    f[22:0]  = 23'($urandom);
    return f;
  endfunction

  // ---------------------------------------------------------------------------
  // D5: e2m1_quantize の全数照合 (仕様書 9.3 節 D5 / 7.2 節の確定表)
  // ---------------------------------------------------------------------------
  task automatic test_d5_unit();
    // G / S の全組合せを踏む代表 frac
    localparam int NF = 11;
    logic [22:0] fr [NF];
    real  v;
    logic [2:0] exp_mag;

    $display("--- D5: e2m1_quantize exhaustive (e_rel x frac) ---");

    fr[0]  = 23'h000000;  // m1=0 g=0 s=0
    fr[1]  = 23'h000001;  // m1=0 g=0 s=1
    fr[2]  = 23'h200000;  // m1=0 g=1 s=0  <- タイ (x.25)
    fr[3]  = 23'h200001;  // m1=0 g=1 s=1
    fr[4]  = 23'h3FFFFF;  // m1=0 g=1 s=1 (上端)
    fr[5]  = 23'h400000;  // m1=1 g=0 s=0  <- x.5 ちょうど
    fr[6]  = 23'h400001;  // m1=1 g=0 s=1
    fr[7]  = 23'h5FFFFF;  // m1=1 g=0 s=1 (上端)
    fr[8]  = 23'h600000;  // m1=1 g=1 s=0  <- タイ (x.75)
    fr[9]  = 23'h600001;  // m1=1 g=1 s=1
    fr[10] = 23'h7FFFFF;  // m1=1 g=1 s=1 (上端)

    q_zero = 1'b0;
    for (int e = -5; e <= 5; e++) begin
      for (int k = 0; k < NF; k++) begin
        q_erel = SCALED_EXP_W'(e);
        q_frac = fr[k];
        #1;
        // scaled 値 = (1 + frac/2^23) * 2^e_rel。double で厳密。
        v = (1.0 + real'(fr[k]) / 8388608.0) * (2.0 ** e);
        exp_mag = ref_quantize_e2m1(v);
        chk3($sformatf("D5 e_rel=%0d frac=%h (v=%0.9f)", e, fr[k], v), q_mag3, exp_mag);
      end
    end

    // is_zero は e_rel によらず 000
    q_zero = 1'b1;
    for (int e = -5; e <= 5; e++) begin
      q_erel = SCALED_EXP_W'(e);
      q_frac = 23'h7FFFFF;
      #1;
      chk3($sformatf("D5 is_zero e_rel=%0d", e), q_mag3, 3'b000);
    end
    q_zero = 1'b0;
  endtask

  // ---------------------------------------------------------------------------
  // D5b: タイ 7 点 ± 1ulp をエンコーダ経由で確認
  //   amax に 6.0 を置くと X_biased = 127 (X = 1.0) となり scaled 値 = 入力値。
  // ---------------------------------------------------------------------------
  task automatic test_d5_block();
    logic [31:0] v [K];
    logic [135:0] blk;
    logic [31:0] tie [7];

    $display("--- D5b: tie points through encoder ---");

    tie[0] = 32'h3E800000;  // 0.25
    tie[1] = 32'h3F400000;  // 0.75
    tie[2] = 32'h3FA00000;  // 1.25
    tie[3] = 32'h3FE00000;  // 1.75
    tie[4] = 32'h40200000;  // 2.5
    tie[5] = 32'h40600000;  // 3.5
    tie[6] = 32'h40A00000;  // 5.0

    // 要素 0 に amax = 6.0、残りにタイ点と ±1ulp を配置する
    for (int d = -1; d <= 1; d++) begin
      for (int i = 0; i < K; i++) v[i] = 32'h00000000;
      v[0] = 32'h40C00000;                       // 6.0 (amax)
      for (int t = 0; t < 7; t++) begin
        v[1 + t]     = 32'(int'(tie[t]) + d);          // +x
        v[1 + 7 + t] = 32'(int'(tie[t]) + d) | 32'h8000_0000;  // -x
      end
      run_enc(v, blk);
      chk($sformatf("D5b tie %0d ulp", d), blk, ref_encode_block(v));
      // tie_hit_dbg: d = 0 (中点ちょうど) の要素だけが 1 になること。
      // 5.0 (tie[6]) は e_rel = 2 かつ m1 = 0 なのでタイ、要素 0 の amax 6.0 は非タイ。
      for (int t = 0; t < 7; t++) begin
        checks++;
        if (tie_obs[1 + t] !== (d == 0)) begin
          errors++;
          $display("[FAIL] D5b tie_hit_dbg[%0d] d=%0d got=%b exp=%b",
                   1 + t, d, tie_obs[1 + t], (d == 0));
        end
      end
      checks++;
      if (tie_obs[0] !== 1'b0) begin
        errors++;
        $display("[FAIL] D5b tie_hit_dbg[0] (amax 6.0) should be 0");
      end
    end

    // 6.0 超 (クランプ) と E==2 の繰り上げ禁止
    for (int i = 0; i < K; i++) v[i] = 32'h00000000;
    v[0] = 32'h41000000;  // 8.0 (amax) -> X = 2.0, scaled 4.0
    v[1] = 32'h40E00000;  // 7.0 -> scaled 3.5 -> タイ -> 4.0 (110)
    v[2] = 32'h40F00000;  // 7.5 -> scaled 3.75 -> 4.0 (110)
    v[3] = 32'h40C00000;  // 6.0 -> scaled 3.0 -> 3.0 (101)
    run_enc(v, blk);
    chk("D5b clamp/no-carry", blk, ref_encode_block(v));
  endtask

  // ---------------------------------------------------------------------------
  // エッジケース (仕様書 7.5 節)
  // ---------------------------------------------------------------------------
  task automatic test_edge();
    logic [31:0] v [K];
    logic [135:0] blk;

    $display("--- Edge: all-zero / NaN / Inf / denormal ---");

    // 全ゼロブロック -> scale 0x00, 要素全 0
    for (int i = 0; i < K; i++) v[i] = 32'h00000000;
    run_enc(v, blk);
    chk("edge all-zero", blk, {8'h00, 128'd0});

    // -0.0 を含む全ゼロブロックでも要素は 0000 (仕様書 7.5 節)
    for (int i = 0; i < K; i++) v[i] = 32'h80000000;
    run_enc(v, blk);
    chk("edge all -0.0", blk, {8'h00, 128'd0});

    // NaN を 1 つ含む -> ブロック単位 scale = 0xFF
    for (int i = 0; i < K; i++) v[i] = 32'h3F800000;
    v[5] = 32'h7FC00000;
    run_enc(v, blk);
    chk("edge NaN", blk, {8'hFF, 128'd0});

    // Inf を 1 つ含む -> 同上
    for (int i = 0; i < K; i++) v[i] = 32'h3F800000;
    v[31] = 32'h7F800000;
    run_enc(v, blk);
    chk("edge Inf", blk, {8'hFF, 128'd0});

    // デノーマルのみ -> DAZ により全ゼロ扱い
    for (int i = 0; i < K; i++) v[i] = 32'h00000001;
    run_enc(v, blk);
    chk("edge denormal(DAZ)", blk, {8'h00, 128'd0});

    // amax が極小 (X_biased 下限 0 クランプ。仕様書 7.5 節 / 12 章 注意 3)
    for (int i = 0; i < K; i++) v[i] = 32'h00000000;
    v[0] = fp32(1'b0, 1, 23'h000000);    // 2^-126
    v[1] = fp32(1'b0, 1, 23'h400000);    // 1.5 * 2^-126
    run_enc(v, blk);
    chk("edge xb clamp low", blk, ref_encode_block(v));
  endtask

  // ---------------------------------------------------------------------------
  // R3: ランダム往復 (仕様書 9.3 節 R3)
  // ---------------------------------------------------------------------------
  int n_clamp, n_flush, n_elem;
  real max_rel_err;

  task automatic test_r3(input int n_iter);
    logic [31:0] v [K];
    logic [135:0] blk;
    real vr, qr, rel;
    int  emin, emax, ex;

    $display("--- R3: random round-trip (%0d blocks) ---", n_iter);

    n_clamp = 0; n_flush = 0; n_elem = 0; max_rel_err = 0.0;

    for (int t = 0; t < n_iter; t++) begin
      // ブロックごとにダイナミックレンジを変える
      emin = $urandom_range(1, 200);
      emax = emin + $urandom_range(0, 40);
      if (emax > 254) emax = 254;
      for (int i = 0; i < K; i++) v[i] = rand_fp32(emin, emax);

      run_enc(v, blk);
      chk($sformatf("R3 block[%0d]", t), blk, ref_encode_block(v));

      // 量子化誤差とクランプ / フラッシュ率の統計
      for (int i = 0; i < K; i++) begin
        if (v[i][30:23] == 8'h00) continue;
        n_elem++;
        vr = fp32_to_real({1'b0, v[i][30:0]});
        // dequant: |P| * X
        ex = int'(blk[135:128]) - 127;
        qr = (real'(dec2_of(blk[4*i +: 4])) / 2.0) * (2.0 ** ex);
        if (qr < 0.0) qr = -qr;
        if (blk[4*i +: 3] == 3'b111) n_clamp++;
        if (blk[4*i +: 3] == 3'b000) n_flush++;
        // 相対誤差は scaled >= 0.75 (= mag3 >= 010) の要素で評価する。
        // それ未満は E2M1 の代表点が疎で、0 や 0.5 への丸めが相対誤差 100% 近くに
        // なり得る (量子化形式固有の性質であり実装誤りではない)。
        if (vr > 0.0 && blk[4*i +: 3] >= 3'b010) begin
          rel = (vr > qr) ? (vr - qr) / vr : (qr - vr) / vr;
          if (rel > max_rel_err) max_rel_err = rel;
        end
      end
    end

    $display("    elements=%0d  clamp(6.0)=%0d (%0.2f%%)  flush(0)=%0d (%0.2f%%)  max|rel err|=%0.4f",
             n_elem, n_clamp, 100.0 * real'(n_clamp) / real'(n_elem),
             n_flush, 100.0 * real'(n_flush) / real'(n_elem), max_rel_err);

    // scaled >= 0.75 の領域での相対誤差上限は 1/3 (v = 0.75 が 1.0 へ丸まる場合)。
    checks++;
    if (max_rel_err > 1.0 / 3.0 + 1.0e-6) begin
      errors++;
      $display("[FAIL] R3 relative error %0.4f exceeds theoretical bound 1/3", max_rel_err);
    end
  endtask

  // ---------------------------------------------------------------------------
  // メイン
  // ---------------------------------------------------------------------------
  int n_r3;

  initial begin
    if (!$value$plusargs("N_R3=%d", n_r3)) n_r3 = 200;

    rst_n    = 1'b0;
    in_valid = 1'b0;
    q_erel   = '0;
    q_frac   = '0;
    q_zero   = 1'b0;
    for (int i = 0; i < K; i++) v_i[i] = 32'h0;
    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    test_d5_unit();
    test_d5_block();
    test_edge();
    test_r3(n_r3);

    $display("=====================================");
    $display(" tb_quant_encoder : %0d checks, %0d errors", checks, errors);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

  initial begin
    #50_000_000;
    $fatal(1, "simulation timeout");
  end

endmodule
