// -----------------------------------------------------------------------------
// hw_top
//   付録A の UVM 環境のトップモジュール (A.3.3)。BDP 単体レベル (図11)。
//   インターフェースを実体化し、uvm_config_db 経由で env へ渡してから
//   run_test() を呼ぶ。
//
//   DUT は mxfp4_bdp 1 つ。エンコーダ / 加算器 / GEMM はそれぞれ別トップに置く
//   (hw_enc_top / hw_add_top / hw_gemm_top)。同一トップに複数 DUT を載せると
//   sukimasim 0.9.9.2 では組合せ評価が収束せず (COMB_EVAL fallback /
//   Combinational settle truncated)、駆動していない DUT の X が観測ポートへ
//   漏れる。テストごとに必要な DUT だけを持つトップを使う。
//
//   駆動信号に宣言時初期値は付けない (README の落とし穴 1)。初期化はここの
//   リセットシーケンスで行う。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module hw_top;
  import uvm_pkg::*;
  import mxfp4_pkg::*;
  import mxfp4_uvm_pkg::*;

  logic clk;
  hw_clkgen u_clkgen (.clk(clk));

  bdp_if bdp_i(clk);

  // ---------------------------------------------------------------------------
  // DUT: mxfp4_bdp
  // ---------------------------------------------------------------------------
  mxfp4_bdp u_bdp (
    .clk             (clk),
    .rst_n           (bdp_i.rst_n),
    .in_valid        (bdp_i.in_valid),
    .in_ready        (bdp_i.in_ready),
    .a_block         (bdp_i.a_block),
    .b_block         (bdp_i.b_block),
    .first           (bdp_i.first),
    .last            (bdp_i.last),
    .out_valid       (bdp_i.out_valid),
    .out_ready       (bdp_i.out_ready),
    .result          (bdp_i.result),
    .sop4_dbg        (bdp_i.sop4_dbg),
    .sop_valid_dbg   (bdp_i.sop_valid_dbg),
    .exp_internal_dbg(bdp_i.exp_internal_dbg),
    .exp_valid_dbg   (bdp_i.exp_valid_dbg),
    .gradual_uf_dbg  ()
  );

  // ---------------------------------------------------------------------------
  // リセットと未駆動信号の初期化
  //   out_ready は 1 固定 (バックプレッシャの検証はプレーン SV 版
  //   tb_bdp_flow が担当する。mxfp4_uvm_if.sv の「追加 2」)。
  // ---------------------------------------------------------------------------
  initial begin
    // 非同期リセット (always_ff @(posedge clk or negedge rst_n)) を確実に効かせる
    // ため、いったん 1 にしてから 0 へ落とす。X -> 0 では negedge イベントが
    // 立たない処理系があり、その場合パイプラインレジスタが X のまま残る。
    bdp_i.rst_n     = 1'b1;
    bdp_i.in_valid  = 1'b0;
    bdp_i.a_block   = '0;
    bdp_i.b_block   = '0;
    bdp_i.first     = 1'b0;
    bdp_i.last      = 1'b0;
    bdp_i.out_ready = 1'b1;
    #1 bdp_i.rst_n = 1'b0;
    repeat (5) @(negedge clk);
    bdp_i.rst_n = 1'b1;
  end

  // ---------------------------------------------------------------------------
  // virtual interface の受け渡しと起動 (A.3.3)
  // ---------------------------------------------------------------------------
  initial begin
    uvm_config_db#(virtual bdp_if)::set(null, "*", "bdp_vif", bdp_i);
    run_test();
  end

endmodule
