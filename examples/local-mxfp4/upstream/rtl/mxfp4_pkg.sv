// -----------------------------------------------------------------------------
// mxfp4_pkg
//   ブロックスケール MXFP4 演算器 共通パッケージ
//   仕様書: docs/mxfp4_spec_rev1.0.md 2 章 (データフォーマット), 3.2 節 (パイプライン)
//
//   構成パラメータは本パッケージから一元配布する (仕様書 12 章 注意 10)。
// -----------------------------------------------------------------------------
package mxfp4_pkg;

  // ---- ブロック構造 (仕様書 2.3 節) ----
  localparam int K       = 32;            // ブロック長 (要素数)
  localparam int ELEMS_W = K * 4;         // 128
  localparam int BLOCK_W = ELEMS_W + 8;   // 136

  typedef logic [3:0] fp4_t;              // E2M1 要素
  typedef logic [7:0] e8m0_t;             // E8M0 共有スケール

  // packed struct の先頭メンバが MSB 側。したがって
  //   block[135:128] = scale, block[127:0] = elems, 要素 i = elems[4*i +: 4]
  typedef struct packed {
    e8m0_t              scale;            // X
    logic [ELEMS_W-1:0] elems;            // Pi (LSB-first パッキング)
  } mxfp4_block_t;

  // ---- パイプライン (仕様書 3.2 節) ----
  // S1 mul / S2 reduce-a / S3 reduce-b / S4 EX1 / S5 EX2 / S6 out
  localparam int LAT = 6;

  // 量子化エンコーダのパイプライン段数 (仕様書 7.6 節)
  // stage1 / stage2 / stage3 / stage4 / stage5
  localparam int ENC_LAT = 5;

  // ---- 特殊値 ----
  localparam e8m0_t        E8M0_NAN  = 8'hFF;        // E8M0 唯一の特殊値 (仕様書 2.2 節)
  localparam logic [31:0]  FP32_QNAN = 32'h7FC0_0000;
  localparam logic [7:0]   FP32_EXP_MAX = 8'hFF;

  // ---- 内部演算幅 (仕様書 5.4 節) ----
  localparam int DEC2_W       = 6;    // signed: value x2  (-12..+12)
  localparam int PROD4_W      = 12;   // signed: value 積 x4 (-144..+144)
  localparam int SOP4_W       = 14;   // signed: Σ x4 (-4608..+4608)
  localparam int SCALED_EXP_W = 10;   // signed: sa + sb - 256 (-256..+252)
  localparam int IEXP_W       = 11;   // signed: 内部拡張指数 (-129..+391)
  localparam int SIGNIF_W     = 24;   // 暗黙 1 + frac23
  localparam int ALIGN_W      = 28;   // carry 1 + 24 + G + R + S

  // E2M1 の絶対値 x2 デコード表 (仕様書 4.2 節)
  //   index = {E[1:0], M}
  function automatic logic [3:0] e2m1_mag2(input logic [2:0] em);
    unique case (em)
      3'b000: e2m1_mag2 = 4'd0;   // 0.0
      3'b001: e2m1_mag2 = 4'd1;   // 0.5 (サブノーマル)
      3'b010: e2m1_mag2 = 4'd2;   // 1.0
      3'b011: e2m1_mag2 = 4'd3;   // 1.5
      3'b100: e2m1_mag2 = 4'd4;   // 2.0
      3'b101: e2m1_mag2 = 4'd6;   // 3.0
      3'b110: e2m1_mag2 = 4'd8;   // 4.0
      3'b111: e2m1_mag2 = 4'd12;  // 6.0
    endcase
  endfunction

endpackage
