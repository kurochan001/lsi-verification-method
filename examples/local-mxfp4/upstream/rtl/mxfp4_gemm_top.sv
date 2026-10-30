// -----------------------------------------------------------------------------
// mxfp4_gemm_top
//   4x4 output-stationary GEMM エンジン。C[MxN] = A[MxK] x B[KxN]
//   (M = ROWS, N = COLS, K = 32 x KBLK)。仕様書 8 章
//
//   A 行ブロックを行方向へブロードキャスト、B 列ブロックを列方向へ流し、
//   全 PE が同一 kblk を同時処理する (スキューなし)。各 PE (= mxfp4_bdp) が
//   出力要素 C[m][n] をローカル FP32 アキュムレータで保持する。
//
//   [出力タイミングの注意]
//     仕様書 8.4 節に従い done は cycle 1 + KBLK + LAT に立つ。一方 8.6 節に
//     従い c_o は出力レジスタなので、done がアサートされたサイクルの末に
//     ラッチされる。したがって **c_o が読めるのは done の次サイクル以降**。
//     結果は次の start まで保持されるので、ホストは done 検出後の任意の
//     サイクルで読み出してよい。
//
//   [ブロックバッファ]
//     仕様書 8.8 節に従い、A/B はレジスタファイル (DMA・ピンポン省略)。
//     リセットを持たないので、start の前に全アドレスへ書き込むこと。
// -----------------------------------------------------------------------------
module mxfp4_gemm_top
  import mxfp4_pkg::*;
#(
  parameter int ROWS = 4,
  parameter int COLS = 4,
  parameter int KBLK = 4,
  // 以下は導出パラメータ。上書きしないこと。
  parameter int A_DEPTH = ROWS * KBLK,
  parameter int B_DEPTH = COLS * KBLK,
  parameter int MAX_DEPTH = (A_DEPTH > B_DEPTH) ? A_DEPTH : B_DEPTH,
  parameter int ADDR_W = (MAX_DEPTH > 1) ? $clog2(MAX_DEPTH) : 1
) (
  input  logic               clk,
  input  logic               rst_n,
  input  logic               start,
  // ---- ブロックバッファ書き込み ----
  input  logic               wr_en,
  input  logic               wr_sel,     // 0: A 側, 1: B 側
  input  logic [ADDR_W-1:0]  wr_addr,    // A: r*KBLK + k, B: c*KBLK + k
  input  logic [BLOCK_W-1:0] wr_data,
  // ---- ステータス / 結果 ----
  output logic               busy,
  output logic               done,
  output logic [31:0]        c_o [ROWS][COLS]
);

  // LAT は mxfp4_pkg から一元配布する (仕様書 12 章 注意 10)
  localparam int PE_LAT = LAT;
  localparam int KB_W   = (KBLK > 1) ? $clog2(KBLK) : 1;

  // ===========================================================================
  // 制御 FSM
  // ===========================================================================
  logic            pe_valid, pe_first, pe_last, c_latch;
  logic [KB_W-1:0] a_kblk, b_kblk;

  gemm_ctrl_fsm #(
    .KBLK(KBLK),
    .LAT (PE_LAT)
  ) u_fsm (
    .clk     (clk),
    .rst_n   (rst_n),
    .start   (start),
    .pe_valid(pe_valid),
    .pe_first(pe_first),
    .pe_last (pe_last),
    .a_kblk  (a_kblk),
    .b_kblk  (b_kblk),
    .c_latch (c_latch),
    .done    (done),
    .busy    (busy)
  );

  // ===========================================================================
  // ブロックバッファ (仕様書 8.8 節: レジスタファイル簡略方式)
  // ===========================================================================
  logic [BLOCK_W-1:0] a_mem [A_DEPTH];
  logic [BLOCK_W-1:0] b_mem [B_DEPTH];
  localparam int A_ADDR_W = A_DEPTH>1 ? $clog2(A_DEPTH) : 1;
  localparam int B_ADDR_W = B_DEPTH>1 ? $clog2(B_DEPTH) : 1;

  always_ff @(posedge clk) begin
    if (wr_en) begin
      // The shared port can be wider than either individual rectangular buffer.
      // Check the full address before narrowing; never wrap an out-of-range write.
      if (wr_sel && int'(wr_addr)<B_DEPTH) b_mem[B_ADDR_W'(wr_addr)] <= wr_data;
      if (!wr_sel && int'(wr_addr)<A_DEPTH) a_mem[A_ADDR_W'(wr_addr)] <= wr_data;
    end
  end

  logic [BLOCK_W-1:0] a_stream [ROWS];
  logic [BLOCK_W-1:0] b_stream [COLS];

  always_comb begin
    for (int r = 0; r < ROWS; r++) a_stream[r] = a_mem[r*KBLK + int'(a_kblk)];
    for (int c = 0; c < COLS; c++) b_stream[c] = b_mem[c*KBLK + int'(b_kblk)];
  end

  // ===========================================================================
  // PE アレイ (4x4 output-stationary)
  // ===========================================================================
  logic [31:0] c_mat     [ROWS][COLS];
  logic        pe_ovalid [ROWS][COLS];

  for (genvar r = 0; r < ROWS; r++) begin : ROW
    for (genvar c = 0; c < COLS; c++) begin : COL
      mxfp4_bdp u_pe (
        .clk             (clk),
        .rst_n           (rst_n),
        .in_valid        (pe_valid),
        .in_ready        (),
        .a_block         (a_stream[r]),
        .b_block         (b_stream[c]),
        .first           (pe_first),
        .last            (pe_last),
        .out_valid       (pe_ovalid[r][c]),
        // GEMM は c_latch で全 PE の結果を同時に取り込むのでバックプレッシャは
        // 生じない。out_ready を 1 に固定すると in_ready も常時 1 になり、
        // ready 拡張前 (仕様書 3.3 節の初期実装) と同一の回路に退化する。
        .out_ready       (1'b1),
        .result          (c_mat[r][c]),
        .sop4_dbg        (),
        .sop_valid_dbg   (),
        .exp_internal_dbg(),
        .exp_valid_dbg   (),
        .gradual_uf_dbg  ()
      );
    end
  end

  // ===========================================================================
  // 出力レジスタ (仕様書 8.6 節: DRAIN 完了時に全並列ラッチ)
  // ===========================================================================
`ifdef MXFP4_ASSERT
  // 仕様書 8.5 節: drain_cnt == LAT-1 で全 PE の pe_ovalid が確定していること。
  // LAT が BDP の実段数とずれると即座に破れる (12 章 注意 10 の機械照合)。
  logic all_ovalid;
  always_comb begin
    all_ovalid = 1'b1;
    for (int r = 0; r < ROWS; r++)
      for (int c = 0; c < COLS; c++) all_ovalid &= pe_ovalid[r][c];
  end

  a_ovalid_at_latch: assert property (@(posedge clk) disable iff (!rst_n)
      c_latch |-> all_ovalid)
    else $error("c_latch asserted while some PE out_valid is low (LAT mismatch?)");
`endif


  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int r = 0; r < ROWS; r++)
        for (int c = 0; c < COLS; c++) c_o[r][c] <= 32'h0000_0000;
    end else if (c_latch) begin
      for (int r = 0; r < ROWS; r++)
        for (int c = 0; c < COLS; c++) c_o[r][c] <= c_mat[r][c];
    end
  end

endmodule
