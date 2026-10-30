// -----------------------------------------------------------------------------
// hw_gemm_top
//   4x4 GEMM レベルの UVM トップ (付録A A.9 方式 Y / 図12)。
//   DUT は mxfp4_gemm_top 1 つだけ。
//
//   [Issue #1320 / #1321 の回避 — 結果は module スコープで畳む]
//     gemm_if は packed の c_flat しか持たない。DUT が要求する
//     2 次元 unpacked 配列はここで宣言し、always_comb で packed へ畳んでから
//     **丸ごと 1 本の assign** で interface へ渡す。
//       - interface の unpacked 配列をポートへ繋ぐと書き込みが届かない (#1320)
//       - interface メンバへ部分選択を左辺にした assign を並べても届かない (#1321)
//     module スコープの packed への部分選択書き込み (always_comb 内) は
//     RTL と同じ普通の書き方で問題なく動く。
//
//   駆動信号に宣言時初期値は付けない (README の落とし穴 1)。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module hw_gemm_top;
  import uvm_pkg::*;
  import mxfp4_pkg::*;
  import mxfp4_uvm_pkg::*;

  localparam int ROWS   = 4;
  localparam int COLS   = 4;
  localparam int KBLK   = 4;
  localparam int ADDR_W = $clog2(ROWS * KBLK);

  logic clk;
  hw_clkgen u_clkgen (.clk(clk));

  // 既定パラメータ (ROWS=4 / COLS=4 / ADDR_W=4) のまま使う。
  // パラメータ付きの virtual interface ハンドルは処理系差が出やすいので、
  // env 側 (env_config) は素の `virtual gemm_if` で受ける。
  gemm_if gemm_i(clk);

  // ---------------------------------------------------------------------------
  // DUT: mxfp4_gemm_top
  // ---------------------------------------------------------------------------
  logic [31:0] c_arr [ROWS][COLS];

  mxfp4_gemm_top #(
    .ROWS (ROWS),
    .COLS (COLS),
    .KBLK (KBLK)
  ) u_gemm (
    .clk     (clk),
    .rst_n   (gemm_i.rst_n),
    .start   (gemm_i.start),
    .wr_en   (gemm_i.wr_en),
    .wr_sel  (gemm_i.wr_sel),
    .wr_addr (gemm_i.wr_addr),
    .wr_data (gemm_i.wr_data),
    .busy    (gemm_i.busy),
    .done    (gemm_i.done),
    .c_o     (c_arr)
  );

  // ---------------------------------------------------------------------------
  // 2 次元 -> packed。要素 (r, c) は [32*(r*COLS + c) +: 32]。
  // ---------------------------------------------------------------------------
  logic [32*ROWS*COLS-1:0] c_flat_w;

  always_comb begin
    for (int r = 0; r < ROWS; r++)
      for (int c = 0; c < COLS; c++)
        c_flat_w[32*(r*COLS + c) +: 32] = c_arr[r][c];
  end

  assign gemm_i.c_flat = c_flat_w;

  // ---------------------------------------------------------------------------
  // リセットと未駆動信号の初期化
  // ---------------------------------------------------------------------------
  initial begin
    gemm_i.rst_n   = 1'b1;
    gemm_i.start   = 1'b0;
    gemm_i.wr_en   = 1'b0;
    gemm_i.wr_sel  = 1'b0;
    gemm_i.wr_addr = '0;
    gemm_i.wr_data = '0;
    #1 gemm_i.rst_n = 1'b0;
    repeat (5) @(negedge clk);
    gemm_i.rst_n = 1'b1;
  end

  // ---------------------------------------------------------------------------
  // virtual interface の受け渡しと起動 (A.3.3)
  // ---------------------------------------------------------------------------
  initial begin
    uvm_config_db#(virtual gemm_if)::set(null, "*", "gemm_vif", gemm_i);
    run_test();
  end

endmodule
