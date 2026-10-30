// -----------------------------------------------------------------------------
// reduce_tree
//   32 個の prod4 (signed 12) を整数加算し SoP4 (signed 14) を得る。
//   log2(32) = 5 段の平衡加算ツリーを 2 パイプライン段 (S2 / S3) に折り畳む。
//     S2: 32 -> 16 -> 8   (段レジスタ)
//     S3:  8 ->  4 -> 2 -> 1 (段レジスタ)
//   最大絶対値 32 x 144 = 4608 なので signed 14bit に収まる。
//   仕様書 4.4 節
//
//   en はパイプラインイネーブル (仕様書 3.3 節の ready 拡張)。0 の間は段
//   レジスタを保持する。ready を使わない構成では 1 に固定してよい。
// -----------------------------------------------------------------------------
module reduce_tree
  import mxfp4_pkg::*;
(
  input  logic                      clk,
  input  logic                      rst_n,
  input  logic                      en,           // パイプラインイネーブル
  input  logic signed [PROD4_W-1:0] prod4_i [K],   // S1 段レジスタ出力
  output logic signed [SOP4_W-1:0]  sop4_o         // S3 段レジスタ出力
);

  logic signed [SOP4_W-1:0] s2_comb [8];
  logic signed [SOP4_W-1:0] s2_q    [8];
  logic signed [SOP4_W-1:0] s3_comb;

  // ---- S2: 32 -> 8 ----
  always_comb begin
    logic signed [SOP4_W-1:0] ext [K];
    logic signed [SOP4_W-1:0] l1  [16];
    // signed 12 -> signed 14 へ符号拡張 (明示キャストで幅拡張の意図を示す)
    for (int i = 0; i < K; i++) ext[i] = SOP4_W'(prod4_i[i]);
    for (int i = 0; i < 16; i++) l1[i] = ext[2*i] + ext[2*i+1];
    for (int i = 0; i < 8;  i++) s2_comb[i] = l1[2*i] + l1[2*i+1];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < 8; i++) s2_q[i] <= '0;
    end else if (en) begin
      for (int i = 0; i < 8; i++) s2_q[i] <= s2_comb[i];
    end
  end

  // ---- S3: 8 -> 1 ----
  always_comb begin
    logic signed [SOP4_W-1:0] l3 [4];
    logic signed [SOP4_W-1:0] l4 [2];
    for (int i = 0; i < 4; i++) l3[i] = s2_q[2*i] + s2_q[2*i+1];
    for (int i = 0; i < 2; i++) l4[i] = l3[2*i] + l3[2*i+1];
    s3_comb = l4[0] + l4[1];
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)   sop4_o <= '0;
    else if (en)  sop4_o <= s3_comb;
  end

endmodule
