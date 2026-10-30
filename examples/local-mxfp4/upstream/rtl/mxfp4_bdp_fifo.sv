// -----------------------------------------------------------------------------
// mxfp4_bdp_fifo
//   mxfp4_bdp の入力側に mxfp4_fifo を置いたエラスティック版ラッパ。
//   仕様書 3.3 節の「ready を追加できる構成」/ 11 章 段階 7。
//
//   目的は 2 つ:
//     1. 下流が out_ready を落としている間に上流が投入したブロックを吸収し、
//        BDP のストールが即座に上流を止めないようにする (スループット確保)。
//     2. 上流から見た in_ready を FIFO の空き (レジスタ出力) だけで決め、
//        BDP が持つ out_ready -> in_ready の組合せパスを切る。
//        AMBA AXI §A3.2.1 は「インタフェースの入力から出力への組合せパスを
//        持たないこと」を要求しており、これを満たす形になる。
//
//   ペイロードは 1 投入分の {a_block, b_block, first, last}。BDP は投入順に
//   累積するので、FIFO が順序を保つ限り結果は ready なし構成とビット一致する。
// -----------------------------------------------------------------------------
module mxfp4_bdp_fifo
  import mxfp4_pkg::*;
#(
  parameter int DEPTH = 4,                            // FIFO 段数 (2 以上)
  // 以下は導出パラメータ。上書きしないこと。
  parameter int PAYLOAD_W = 2*BLOCK_W + 2,
  parameter int CNT_W     = $clog2(DEPTH + 1)
) (
  input  logic               clk,
  input  logic               rst_n,
  // ---- 上流 ----
  input  logic               in_valid,
  output logic               in_ready,
  input  logic [BLOCK_W-1:0] a_block,
  input  logic [BLOCK_W-1:0] b_block,
  input  logic               first,
  input  logic               last,
  // ---- 下流 ----
  output logic               out_valid,
  input  logic               out_ready,
  output logic [31:0]        result,
  // ---- 観測ポート (合成時は削除可) ----
  output logic [CNT_W-1:0]   fifo_level_dbg,
  output logic               pe_in_valid_dbg,   // FIFO -> BDP の投入
  output logic               pe_in_ready_dbg
);

  logic [PAYLOAD_W-1:0] wr_data, rd_data;
  logic                 pe_valid, pe_ready;

  assign wr_data = {a_block, b_block, first, last};

  mxfp4_fifo #(
    .WIDTH(PAYLOAD_W),
    .DEPTH(DEPTH)
  ) u_fifo (
    .clk      (clk),
    .rst_n    (rst_n),
    .wr_valid (in_valid),
    .wr_ready (in_ready),
    .wr_data  (wr_data),
    .rd_valid (pe_valid),
    .rd_ready (pe_ready),
    .rd_data  (rd_data),
    .level_dbg(fifo_level_dbg)
  );

  mxfp4_bdp u_bdp (
    .clk             (clk),
    .rst_n           (rst_n),
    .in_valid        (pe_valid),
    .in_ready        (pe_ready),
    .a_block         (rd_data[PAYLOAD_W-1 -: BLOCK_W]),
    .b_block         (rd_data[2 +: BLOCK_W]),
    .first           (rd_data[1]),
    .last            (rd_data[0]),
    .out_valid       (out_valid),
    .out_ready       (out_ready),
    .result          (result),
    .sop4_dbg        (),
    .sop_valid_dbg   (),
    .exp_internal_dbg(),
    .exp_valid_dbg   (),
    .gradual_uf_dbg  ()
  );

  assign pe_in_valid_dbg = pe_valid;
  assign pe_in_ready_dbg = pe_ready;

endmodule
