// -----------------------------------------------------------------------------
// hw_enc_top
//   量子化エンコーダ単体レベルの UVM トップ (付録A A.3.3 / 図11 の enc env)。
//   DUT は quant_encoder 1 つだけ。BDP / 加算器 / GEMM はそれぞれ別トップに置く
//   (hw_top / hw_add_top / hw_gemm_top)。同一トップに複数 DUT を載せると
//   sukimasim 0.9.9.2 では組合せ評価が収束せず、駆動していない DUT の X が
//   観測ポートへ漏れる。
//
//   UNBIASED_34 は既定の 0 (仕様書 7.1 節 Algorithm 1)。段階 7 の 7.7 節を
//   検証する版は別トップを立てること (既定値は変えない)。
//
//   [Issue #1320 の回避 — unpacked 配列は module スコープに置く]
//     enc_if は packed ベクタしか持たない。DUT が要求する unpacked 配列は
//     ここで宣言し、always_comb で展開 (入力) / 収集 (観測ポート) する。
//     interface の unpacked 配列をポートへ繋ぐと書き込みが届かず、DUT が
//     全ゼロを受け取る (mxfp4_uvm_if.sv の enc_if 冒頭を参照)。
//     module スコープの unpacked 配列はポートへ繋いでも正しく動く。
//
//   駆動信号に宣言時初期値は付けない (README の落とし穴 1)。初期化はここの
//   リセットシーケンスで行う。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module hw_enc_top;
  import uvm_pkg::*;
  import mxfp4_pkg::*;
  import mxfp4_uvm_pkg::*;

  logic clk;
  // クロック生成はサブモジュールへ (Issue #1176。hw_top と同じ理由)
  hw_clkgen u_clkgen (.clk(clk));

  enc_if enc_i(clk);

  // ---------------------------------------------------------------------------
  // packed <-> unpacked の変換 (module スコープ)
  //   要素 i は enc_if 側と同じく [W*i +: W] に置く。
  // ---------------------------------------------------------------------------
  logic [31:0]                    v_i_arr   [K];
  logic signed [SCALED_EXP_W-1:0] e_rel_arr [K];
  logic [2:0]                     mag3_arr  [K];
  logic                           tie_arr   [K];

  // packed <-> unpacked は genvar + continuous assign で行う。
  //   always_comb + 可変インデックスで unpacked 配列の要素へ書くと、
  //   sukimasim 0.9.9.2 では代入が届かない (v_i_arr が全ゼロのままになる)。
  //   genvar なら要素ごとに定数インデックスの assign になり、正しく動く。
  //   driver は {>>{tr.v}} で詰めるので、要素 0 が最上位側に入る。
  for (genvar gi = 0; gi < K; gi++) begin : g_unpack
    assign v_i_arr[gi] = enc_i.v_flat[32*(K-1-gi) +: 32];
  end

  // 観測ポート: 配列 -> flat
  //   interface のメンバへ部分選択を左辺にした assign を並べると届かないので、
  //   いったん module スコープの packed 変数へ組み立て、**丸ごと 1 本の assign** で
  //   interface へ渡す。module スコープの packed への部分選択書き込みは
  //   RTL と同じ普通の書き方で問題なく動く。
  logic [SCALED_EXP_W*K-1:0] e_rel_flat_w;
  logic [3*K-1:0]            mag3_flat_w;
  logic [K-1:0]              tie_flat_w;

  always_comb begin
    for (int i = 0; i < K; i++) begin
      e_rel_flat_w[SCALED_EXP_W*i +: SCALED_EXP_W] = e_rel_arr[i];
      mag3_flat_w [3*i +: 3]                       = mag3_arr[i];
      tie_flat_w  [i]                              = tie_arr[i];
    end
  end

  assign enc_i.e_rel_flat = e_rel_flat_w;
  assign enc_i.mag3_flat  = mag3_flat_w;
  assign enc_i.tie_flat   = tie_flat_w;

  // ---------------------------------------------------------------------------
  // DUT: quant_encoder
  // ---------------------------------------------------------------------------
  quant_encoder #(
    .UNBIASED_34 (1'b0)
  ) u_enc (
    .clk             (clk),
    .rst_n           (enc_i.rst_n),
    .in_valid        (enc_i.in_valid),
    .v_i             (v_i_arr),
    .blk_o           (enc_i.blk_o),
    .out_valid       (enc_i.out_valid),
    .e_rel_dbg       (e_rel_arr),
    .mag3_dbg        (mag3_arr),
    .tie_hit_dbg     (tie_arr),
    .quant_valid_dbg (enc_i.quant_valid_dbg)
  );

  // ---------------------------------------------------------------------------
  // リセットと未駆動信号の初期化
  //   非同期リセットの negedge を確実に作るため 1 -> 0 -> 1 と動かす
  //   (X -> 0 では negedge イベントが立たない処理系がある)。
  // ---------------------------------------------------------------------------
  initial begin
    enc_i.rst_n    = 1'b1;
    enc_i.in_valid = 1'b0;
    enc_i.v_flat   = '0;
    #1 enc_i.rst_n = 1'b0;
    repeat (5) @(negedge clk);
    enc_i.rst_n = 1'b1;
  end

  // ---------------------------------------------------------------------------
  // virtual interface の受け渡しと起動 (A.3.3)
  // ---------------------------------------------------------------------------
  initial begin
    uvm_config_db#(virtual enc_if)::set(null, "*", "enc_vif", enc_i);
    run_test();
  end

endmodule
