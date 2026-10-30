// -----------------------------------------------------------------------------
// tb_mxfp4_bdp
//   ブロック内積ユニットのテストベンチ。仕様書 9.3 節のシナリオ D1〜D4 /
//   R1 / R2a〜R2d / E1 / E2 を実装する。
//
//   本 TB はプレーン SystemVerilog (class / covergroup / SVA 非依存) で書いて
//   あり、Icarus Verilog・Verilator でも実行できる。仕様書 9.1 節のクラス
//   ベース TB (mailbox / 制約付きランダム / covergroup / SVA) は sukimasim 向け
//   の拡張として別途用意する。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_mxfp4_bdp #(
  // -GUSE_NEARFAR=1 で near/far 二経路版の加算器に差し替える (仕様書 5.7 節)
  parameter bit USE_NEARFAR = 1'b0
);

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  // ---------------------------------------------------------------------------
  // クロック / リセット
  // ---------------------------------------------------------------------------
  logic clk;
  logic rst_n;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // ---------------------------------------------------------------------------
  // DUT
  // ---------------------------------------------------------------------------
  logic                     in_valid, in_ready, first, last, out_valid;
  logic [BLOCK_W-1:0]       a_block, b_block;
  logic [31:0]              result;
  logic signed [SOP4_W-1:0] sop4_dbg;
  logic                     sop_valid_dbg;
  logic signed [IEXP_W-1:0] exp_internal_dbg;
  logic                     exp_valid_dbg;

  mxfp4_bdp #(.USE_NEARFAR(USE_NEARFAR)) dut (
    .clk             (clk),
    .rst_n           (rst_n),
    .in_valid        (in_valid),
    .in_ready        (in_ready),
    .a_block         (a_block),
    .b_block         (b_block),
    .first           (first),
    .last            (last),
    .out_valid       (out_valid),
    .out_ready       (1'b1),          // 本 TB はバックプレッシャを掛けない
    .result          (result),
    .sop4_dbg        (sop4_dbg),
    .sop_valid_dbg   (sop_valid_dbg),
    .exp_internal_dbg(exp_internal_dbg),
    .exp_valid_dbg   (exp_valid_dbg),
    .gradual_uf_dbg  ()
  );

  // D1 用に e2m1_decode を単体でもインスタンス化する
  logic [3:0]               d1_code;
  logic signed [DEC2_W-1:0] d1_dec2;
  logic                     d1_zero;

  e2m1_decode u_d1 (
    .code_i   (d1_code),
    .dec2_o   (d1_dec2),
    .is_zero_o(d1_zero)
  );

  // ---------------------------------------------------------------------------
  // スコアボード
  // ---------------------------------------------------------------------------
  int checks = 0;
  int errors = 0;

  task automatic chk32(input string name, input logic [31:0] got, input logic [31:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      $display("[FAIL] %s : got=%h exp=%h", name, got, exp);
    end
  endtask

  task automatic chk_int(input string name, input int got, input int exp);
    checks++;
    if (got != exp) begin
      errors++;
      $display("[FAIL] %s : got=%0d exp=%0d", name, got, exp);
    end
  endtask

  // SoP4 を S3 段のタイミングで採取する (仕様書 9.2 節: ブロック内は整数厳密照合)
  int sop4_obs [$];
  always @(posedge clk) begin
    if (rst_n && sop_valid_dbg) sop4_obs.push_back(int'(sop4_dbg));
  end

  // ---------------------------------------------------------------------------
  // ブロック生成ヘルパー
  // ---------------------------------------------------------------------------
  function automatic logic [135:0] mk_block(input logic [7:0] scale, input logic [3:0] e [32]);
    logic [127:0] el;
    for (int i = 0; i < 32; i++) el[4*i +: 4] = e[i];
    return {scale, el};
  endfunction

  function automatic logic [135:0] mk_uniform(input logic [7:0] scale, input logic [3:0] code);
    logic [3:0] e [32];
    for (int i = 0; i < 32; i++) e[i] = code;
    return mk_block(scale, e);
  endfunction

  function automatic logic [135:0] mk_rand(input logic [7:0] scale);
    logic [3:0] e [32];
    for (int i = 0; i < 32; i++) e[i] = 4'($urandom_range(0, 15));
    return mk_block(scale, e);
  endfunction

  // 要素 idx のみ code、他は 0 のブロック
  function automatic logic [135:0] mk_single(input logic [7:0] scale, input int idx,
                                             input logic [3:0] code);
    logic [3:0] e [32];
    for (int i = 0; i < 32; i++) e[i] = (i == idx) ? code : 4'h0;
    return mk_block(scale, e);
  endfunction

  // scaled_exp = sa + sb - 256 を満たす (sa, sb) を作る
  task automatic split_scale(input int sexp, output logic [7:0] sa, output logic [7:0] sb);
    int sum;
    sum = sexp + 256;
    if (sum < 0)        begin sa = 8'd0;   sb = 8'd0;   end   // 範囲外 (呼び出し側で回避)
    else if (sum <= 254) begin sa = 8'(sum); sb = 8'd0;  end
    else                 begin sa = 8'd254; sb = 8'(sum - 254); end
  endtask

  // ---------------------------------------------------------------------------
  // 駆動タスク
  //   ブロック列を 1 サイクル 1 ペアで投入し、LAT サイクル後の result を返す。
  //   レイテンシが厳密に LAT であること (早すぎ / 遅すぎ) も検査する。
  // ---------------------------------------------------------------------------
  task automatic run_series(input logic [135:0] a [], input logic [135:0] b [],
                            output logic [31:0] res);
    int n;
    n = a.size();
    for (int j = 0; j < n; j++) begin
      @(negedge clk);
      in_valid = 1'b1;
      a_block  = a[j];
      b_block  = b[j];
      first    = (j == 0);
      last     = (j == n-1);
    end
    @(negedge clk);
    in_valid = 1'b0;
    first    = 1'b0;
    last     = 1'b0;

    // ここまでで last をサンプルする posedge (レイテンシ計数の起点) は消化済み。
    // out_valid はさらに LAT-1 個の posedge の後に立つ。
    repeat (LAT - 2) @(posedge clk);
    #1;
    checks++;
    if (out_valid) begin
      errors++;
      $display("[FAIL] out_valid asserted earlier than LAT=%0d", LAT);
    end
    @(posedge clk);
    #1;
    checks++;
    if (!out_valid) begin
      errors++;
      $display("[FAIL] out_valid not asserted at LAT=%0d", LAT);
    end
    res = result;
  endtask

  // 単一ブロックを投入して結果を得る簡易版
  task automatic run_one(input logic [135:0] a, input logic [135:0] b,
                         output logic [31:0] res);
    logic [135:0] aa [], bb [];
    aa = new[1]; bb = new[1];
    aa[0] = a;   bb[0] = b;
    run_series(aa, bb, res);
  endtask

  // ---------------------------------------------------------------------------
  // D1: e2m1_decode 全 16 コード (仕様書 2.1 節の表)
  // ---------------------------------------------------------------------------
  task automatic test_d1();
    $display("--- D1: e2m1_decode ---");
    for (int c = 0; c < 16; c++) begin
      d1_code = 4'(c);
      #1;
      chk_int($sformatf("D1 dec2[%0d]", c), int'(d1_dec2), dec2_of(4'(c)));
      checks++;
      if (d1_zero !== (dec2_of(4'(c)) == 0)) begin
        errors++;
        $display("[FAIL] D1 is_zero[%0d]", c);
      end
    end
  endtask

  // ---------------------------------------------------------------------------
  // D2: elem_mul + reduce_tree の SoP4 境界 (仕様書 9.3 節 D2)
  // ---------------------------------------------------------------------------
  task automatic test_d2();
    logic [31:0] r;
    logic [135:0] a, b;
    $display("--- D2: SoP4 boundary ---");

    sop4_obs.delete();

    // 全ゼロ -> SoP4 = 0
    a = mk_uniform(8'd127, 4'b0000);
    b = mk_uniform(8'd127, 4'b0000);
    run_one(a, b, r);

    // 全 +6 x +6 -> 32 * 12 * 12 = 4608
    a = mk_uniform(8'd127, 4'b0111);
    b = mk_uniform(8'd127, 4'b0111);
    run_one(a, b, r);

    // 全 -6 x +6 -> -4608
    a = mk_uniform(8'd127, 4'b1111);
    b = mk_uniform(8'd127, 4'b0111);
    run_one(a, b, r);

    // 単一要素のみ非ゼロ (+1.5 x -3.0 = -4.5 -> dec2 3 * -6 = -18)
    a = mk_single(8'd127, 7, 4'b0011);
    b = mk_single(8'd127, 7, 4'b1101);
    run_one(a, b, r);

    chk_int("D2 sop4 all-zero",  sop4_obs[0], 0);
    chk_int("D2 sop4 +6*+6",     sop4_obs[1], 4608);
    chk_int("D2 sop4 -6*+6",     sop4_obs[2], -4608);
    chk_int("D2 sop4 single",    sop4_obs[3], -18);
  endtask

  // ---------------------------------------------------------------------------
  // D3: scale_add / NaN (仕様書 9.3 節 D3)
  // ---------------------------------------------------------------------------
  task automatic test_d3();
    logic [31:0] r;
    logic [135:0] a, b;
    logic [135:0] aa [], bb [];
    $display("--- D3: scale NaN / boundary ---");

    // sa = 0xFF -> NaN
    a = mk_uniform(8'hFF, 4'b0010);
    b = mk_uniform(8'd127, 4'b0010);
    run_one(a, b, r);
    chk32("D3 nan(sa)", r, QNAN);

    // sb = 0xFF -> NaN
    a = mk_uniform(8'd127, 4'b0010);
    b = mk_uniform(8'hFF, 4'b0010);
    run_one(a, b, r);
    chk32("D3 nan(sb)", r, QNAN);

    // NaN は以降のブロックでも伝播する
    aa = new[2]; bb = new[2];
    aa[0] = mk_uniform(8'hFF,  4'b0010); bb[0] = mk_uniform(8'd127, 4'b0010);
    aa[1] = mk_uniform(8'd127, 4'b0010); bb[1] = mk_uniform(8'd127, 4'b0010);
    run_series(aa, bb, r);
    chk32("D3 nan propagate", r, ref_dot_series(aa, bb));

    // scale 境界 0x00 / 0xFE
    a = mk_uniform(8'h00, 4'b0010);
    b = mk_uniform(8'h00, 4'b0010);
    run_one(a, b, r);
    chk32("D3 scale 0x00", r, ref_fp32_add_term(32'h0, ref_sop4(a, b), -256));

    a = mk_uniform(8'hFE, 4'b0010);
    b = mk_uniform(8'hFE, 4'b0010);
    run_one(a, b, r);
    chk32("D3 scale 0xFE", r, ref_fp32_add_term(32'h0, ref_sop4(a, b), 252));
  endtask

  // ---------------------------------------------------------------------------
  // D4: first/last と KBLK = 1 / 2 / 3 の累積 (仕様書 9.3 節 D4)
  // ---------------------------------------------------------------------------
  task automatic test_d4();
    logic [31:0] r;
    logic [135:0] aa [], bb [];
    $display("--- D4: first/last accumulation ---");
    for (int n = 1; n <= 3; n++) begin
      aa = new[n]; bb = new[n];
      for (int j = 0; j < n; j++) begin
        aa[j] = mk_rand(8'd127);
        bb[j] = mk_rand(8'd127);
      end
      run_series(aa, bb, r);
      chk32($sformatf("D4 KBLK=%0d", n), r, ref_dot_series(aa, bb));
    end
  endtask

  // ---------------------------------------------------------------------------
  // E1: 全ゼロブロック -> +0 (仕様書 9.3 節 E1)
  // ---------------------------------------------------------------------------
  task automatic test_e1();
    logic [31:0] r;
    logic [135:0] a, b;
    $display("--- E1: all zero ---");
    a = mk_uniform(8'd127, 4'b0000);
    b = mk_uniform(8'd127, 4'b0000);
    run_one(a, b, r);
    chk32("E1 all-zero", r, 32'h0000_0000);
  endtask

  // ---------------------------------------------------------------------------
  // E2: 相殺 (仕様書 9.3 節 E2)
  // ---------------------------------------------------------------------------
  task automatic test_e2();
    logic [31:0] r;
    logic [3:0]  ea [32], eb [32];
    logic [135:0] a, b;
    logic [135:0] aa [], bb [];
    $display("--- E2: cancellation ---");

    // ブロック内で SoP4 = 0 になる配置 (+x と -x のペア)
    for (int i = 0; i < 32; i++) begin
      ea[i] = (i % 2 == 0) ? 4'b0111 : 4'b1111;   // +6, -6
      eb[i] = 4'b0111;                             // +6
    end
    a = mk_block(8'd127, ea);
    b = mk_block(8'd127, eb);
    run_one(a, b, r);
    chk32("E2 sop4=0", r, 32'h0000_0000);

    // ブロック間の完全相殺: +X と -X を連続投入 -> +0 (RNE)
    aa = new[2]; bb = new[2];
    aa[0] = mk_uniform(8'd127, 4'b0111); bb[0] = mk_uniform(8'd127, 4'b0111);
    aa[1] = mk_uniform(8'd127, 4'b1111); bb[1] = mk_uniform(8'd127, 4'b0111);
    run_series(aa, bb, r);
    chk32("E2 acc cancel", r, 32'h0000_0000);
  endtask

  // ---------------------------------------------------------------------------
  // R1: ランダム (スケール固定 127)、SoP4 整数照合 (仕様書 9.3 節 R1)
  // ---------------------------------------------------------------------------
  task automatic test_r1(input int n_block);
    logic [31:0] r;
    logic [135:0] aa [], bb [];
    int exp_sop4 [$];
    $display("--- R1: random SoP4 (%0d blocks) ---", n_block);

    sop4_obs.delete();
    exp_sop4.delete();

    for (int t = 0; t < n_block; t++) begin
      aa = new[1]; bb = new[1];
      aa[0] = mk_rand(8'd127);
      bb[0] = mk_rand(8'd127);
      exp_sop4.push_back(ref_sop4(aa[0], bb[0]));
      run_series(aa, bb, r);
      chk32($sformatf("R1 result[%0d]", t), r, ref_dot_series(aa, bb));
    end

    checks++;
    if (sop4_obs.size() != exp_sop4.size()) begin
      errors++;
      $display("[FAIL] R1 sop4 sample count %0d != %0d", sop4_obs.size(), exp_sop4.size());
    end else begin
      for (int t = 0; t < exp_sop4.size(); t++)
        chk_int($sformatf("R1 sop4[%0d]", t), sop4_obs[t], exp_sop4[t]);
    end
  endtask

  // ---------------------------------------------------------------------------
  // R2a: 範囲内のランダム累積、FP32 ビット照合 (仕様書 9.3 節 R2a)
  // ---------------------------------------------------------------------------
  task automatic test_r2a(input int n_series);
    logic [31:0] r;
    logic [135:0] aa [], bb [];
    logic [7:0] sa, sb;
    int n, sexp;
    $display("--- R2a: random accumulation (%0d series) ---", n_series);
    for (int t = 0; t < n_series; t++) begin
      n  = $urandom_range(1, 6);
      aa = new[n]; bb = new[n];
      for (int j = 0; j < n; j++) begin
        // scaled_exp を -120..+110 に制約する (仕様書 R2a)
        sexp = $urandom_range(0, 230) - 120;
        split_scale(sexp, sa, sb);
        aa[j] = mk_rand(sa);
        bb[j] = mk_rand(sb);
      end
      run_series(aa, bb, r);
      chk32($sformatf("R2a series[%0d]", t), r, ref_dot_series(aa, bb));
    end
  endtask

  // ---------------------------------------------------------------------------
  // R2b: オーバーフロー -> ±Inf 飽和 (仕様書 9.3 節 R2b)
  // ---------------------------------------------------------------------------
  task automatic test_r2b();
    logic [31:0] r;
    logic [135:0] a, b;
    logic [7:0] sa, sb;
    $display("--- R2b: overflow ---");
    for (int s = 0; s < 2; s++) begin
      for (int sexp = 200; sexp <= 252; sexp += 13) begin
        split_scale(sexp, sa, sb);
        a = mk_uniform(sa, s ? 4'b1111 : 4'b0111);   // -6 or +6
        b = mk_uniform(sb, 4'b0111);
        run_one(a, b, r);
        chk32($sformatf("R2b sign=%0d sexp=%0d", s, sexp), r,
              ref_fp32_add_term(32'h0, ref_sop4(a, b), sexp));
      end
    end
  endtask

  // ---------------------------------------------------------------------------
  // R2c: アンダーフロー -> FTZ ±0 (仕様書 9.3 節 R2c)
  // ---------------------------------------------------------------------------
  task automatic test_r2c();
    logic [31:0] r;
    logic [135:0] a, b;
    logic [7:0] sa, sb;
    $display("--- R2c: underflow (FTZ) ---");
    for (int s = 0; s < 2; s++) begin
      for (int sexp = -256; sexp <= -200; sexp += 13) begin
        split_scale(sexp, sa, sb);
        a = mk_uniform(sa, s ? 4'b1111 : 4'b0111);
        b = mk_uniform(sb, 4'b0111);
        run_one(a, b, r);
        chk32($sformatf("R2c sign=%0d sexp=%0d", s, sexp), r,
              ref_fp32_add_term(32'h0, ref_sop4(a, b), sexp));
      end
    end
  endtask

  // ---------------------------------------------------------------------------
  // R2d: 境界近傍の指数遷移 (仕様書 9.3 節 R2d)
  //   e_conv = p + 127 + scaled_exp が 0/1/2 および 253/254/255 近傍になる
  //   scaled_exp を選び、丸め繰り上がりによる指数遷移を確認する。
  // ---------------------------------------------------------------------------
  task automatic test_r2d();
    logic [31:0] r;
    logic [135:0] a, b;
    logic [135:0] aa [], bb [];
    logic [7:0] sa, sb;
    int p, sexp;
    $display("--- R2d: exponent boundary ---");

    // 全要素 +6 x +6 -> SoP4 = 4608 = 2^12 + 2^9 なので p = 12
    p = 12;
    for (int target = -2; target <= 3; target++) begin
      sexp = target - 127 - p;
      if (sexp >= -256) begin
        split_scale(sexp, sa, sb);
        a = mk_uniform(sa, 4'b0111);
        b = mk_uniform(sb, 4'b0111);
        run_one(a, b, r);
        chk32($sformatf("R2d low e_conv=%0d", target), r,
              ref_fp32_add_term(32'h0, ref_sop4(a, b), sexp));
      end
    end
    for (int target = 252; target <= 256; target++) begin
      sexp = target - 127 - p;
      if (sexp <= 252) begin
        split_scale(sexp, sa, sb);
        a = mk_uniform(sa, 4'b0111);
        b = mk_uniform(sb, 4'b0111);
        run_one(a, b, r);
        chk32($sformatf("R2d high e_conv=%0d", target), r,
              ref_fp32_add_term(32'h0, ref_sop4(a, b), sexp));
      end
    end

    // 累積で丸め繰り上がりが指数を 1 上げるケース:
    //   大きい項に、その ulp の半分ちょうどより上の項を足す
    for (int d = 20; d <= 26; d++) begin
      aa = new[2]; bb = new[2];
      split_scale(0, sa, sb);
      aa[0] = mk_uniform(sa, 4'b0111); bb[0] = mk_uniform(sb, 4'b0111);
      split_scale(-d, sa, sb);
      aa[1] = mk_uniform(sa, 4'b0111); bb[1] = mk_uniform(sb, 4'b0111);
      run_series(aa, bb, r);
      chk32($sformatf("R2d round-carry d=%0d", d), r, ref_dot_series(aa, bb));
    end
  endtask

  // ---------------------------------------------------------------------------
  // R2e: アライン量を制御した累積 (桁上げ時の sticky 保存を検査)
  //
  //   R2a は各ブロックの scaled_exp を独立一様にとるため、隣接ブロック間の指数差が
  //   ほぼ常に大きくなり (平均 100 超)、アライン量 26 で飽和する領域しか踏まない。
  //   実効加算で桁上げが出たときに押し出される sticky ビット (仕様書 5.3 節 5.
  //   「押し出しビットを sticky へ OR」) が丸めに効くのは指数差が中程度のときだけ
  //   なので、ここでは差 d を 0..30 で掃引する。
  //
  //   term の有効仮数は i2f 由来で下位 11bit 以上が必ず 0 になるため、d が小さいと
  //   sticky = 0、d >= 26 だと飽和して guard = 0 になる。差が出るのはその間の帯。
  // ---------------------------------------------------------------------------
  task automatic test_r2e(input int n_iter);
    logic [31:0] r;
    logic [135:0] aa [], bb [];
    logic [7:0] sa, sb;
    int n;
    $display("--- R2e: controlled align distance (sticky on carry) ---");
    for (int d = 0; d <= 30; d++) begin
      for (int t = 0; t < n_iter; t++) begin
        n  = $urandom_range(2, 4);
        aa = new[n];
        bb = new[n];
        for (int j = 0; j < n; j++) begin
          // 先頭ブロックを基準に、以降を d ずつ下げる
          split_scale(-d * j, sa, sb);
          aa[j] = mk_rand(sa);
          bb[j] = mk_rand(sb);
        end
        run_series(aa, bb, r);
        chk32($sformatf("R2e d=%0d[%0d]", d, t), r, ref_dot_series(aa, bb));
      end
    end
  endtask

  // ---------------------------------------------------------------------------
  // メイン
  // ---------------------------------------------------------------------------
  int n_r1, n_r2a, n_r2e;

  initial begin
    if (!$value$plusargs("N_R1=%d",  n_r1))  n_r1  = 200;
    if (!$value$plusargs("N_R2A=%d", n_r2a)) n_r2a = 200;
    if (!$value$plusargs("N_R2E=%d", n_r2e)) n_r2e = 40;

    rst_n    = 1'b0;
    in_valid = 1'b0;
    first    = 1'b0;
    last     = 1'b0;
    a_block  = '0;
    b_block  = '0;
    repeat (5) @(negedge clk);
    rst_n = 1'b1;
    repeat (2) @(negedge clk);

    test_d1();
    test_d2();
    test_d3();
    test_d4();
    test_e1();
    test_e2();
    test_r1(n_r1);
    test_r2a(n_r2a);
    test_r2b();
    test_r2c();
    test_r2d();
    test_r2e(n_r2e);

    $display("=====================================");
    $display(" tb_mxfp4_bdp : %0d checks, %0d errors", checks, errors);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    if (errors != 0) $fatal(1, "self-check failed: %0d errors", errors);
    $finish;
  end

  // タイムアウト
  initial begin
    #50_000_000;
    $fatal(1, "simulation timeout");
  end

endmodule
