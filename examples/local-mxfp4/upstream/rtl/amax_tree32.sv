// -----------------------------------------------------------------------------
// amax_tree32
//   32 入力の絶対値最大値 (amax) を求めるトーナメント。
//   IEEE 754 のバイアス指数採用により、符号ビットを落とした 31bit を符号なし
//   整数として比較すると絶対値の大小と単調に一致する (仕様書 7.4 節)。
//
//   5 段のトーナメントを 2 パイプライン段 (stage2 / stage3) に折り畳む
//   (仕様書 7.6 節のパイプライン表)。
//     stage2: 32 -> 16 -> 8  (段レジスタ)
//     stage3:  8 ->  4 -> 2 -> 1 (段レジスタ)
// -----------------------------------------------------------------------------
module amax_tree32
  import mxfp4_pkg::*;
(
  input  logic        clk,
  input  logic        rst_n,
  input  logic [30:0] key_i [K],   // 符号ビットを除いた 31bit
  output logic [30:0] amax_o
);

  logic [30:0] s2_comb [8];
  logic [30:0] s2_q    [8];
  logic [30:0] s3_comb;

  always_comb begin
    logic [30:0] l1 [16];
    for (int i = 0; i < 16; i++) l1[i]      = (key_i[2*i] > key_i[2*i+1]) ? key_i[2*i] : key_i[2*i+1];
    for (int i = 0; i < 8;  i++) s2_comb[i] = (l1[2*i]    > l1[2*i+1])    ? l1[2*i]    : l1[2*i+1];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < 8; i++) s2_q[i] <= '0;
    end else begin
      for (int i = 0; i < 8; i++) s2_q[i] <= s2_comb[i];
    end
  end

  always_comb begin
    logic [30:0] l3 [4];
    logic [30:0] l4 [2];
    for (int i = 0; i < 4; i++) l3[i] = (s2_q[2*i] > s2_q[2*i+1]) ? s2_q[2*i] : s2_q[2*i+1];
    for (int i = 0; i < 2; i++) l4[i] = (l3[2*i]   > l3[2*i+1])   ? l3[2*i]   : l3[2*i+1];
    s3_comb = (l4[0] > l4[1]) ? l4[0] : l4[1];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) amax_o <= '0;
    else        amax_o <= s3_comb;
  end

endmodule
