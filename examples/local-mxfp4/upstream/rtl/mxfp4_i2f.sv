// -----------------------------------------------------------------------------
// mxfp4_i2f
//   int14 (SoP4) + scaled_exp -> 内部拡張 FP32 (符号 / signed 11bit 指数 /
//   暗黙 1 込み 24bit 有効仮数) への変換。組合せ回路 (S4 = EX1 内)。
//   仕様書 5.2 節 / 5.6 節
//
//   変換が厳密である根拠 (仕様書 5.2 節):
//     SoP4 の最大絶対値 4608 は有効ビット数 13。FP32 の有効仮数は暗黙ビット
//     込み 24bit なので、ゼロ拡張だけで仮数枠に収まり GRS がすべて 0 になる。
//     したがって i2f 単体では丸めが発生しない。
// -----------------------------------------------------------------------------
module mxfp4_i2f
  import mxfp4_pkg::*;
(
  input  logic signed [SOP4_W-1:0]       sop4_i,
  input  logic signed [SCALED_EXP_W-1:0] scaled_exp_i,
  input  logic                           nan_i,
  output logic                           sign_o,
  output logic signed [IEXP_W-1:0]       exp_o,      // p + 127 + scaled_exp
  output logic [SIGNIF_W-1:0]            signif_o,   // 暗黙 1 込み 24bit
  output logic                           zero_o,
  output logic                           nan_o
);

  logic [12:0] mag13;
  logic [3:0]  clz;
  logic [3:0]  p;

  always_comb begin
    sign_o = sop4_i[SOP4_W-1];
    // 絶対値化。-4608..+4608 の絶対値は 13bit に収まる。
    mag13  = sop4_i[SOP4_W-1] ? (~sop4_i[12:0] + 13'd1) : sop4_i[12:0];
    zero_o = (mag13 == 13'd0);
    nan_o  = nan_i;

    // 先頭ゼロ数 (13bit)。合成時は優先エンコーダへ展開される。
    clz = 4'd12;
    for (int i = 12; i >= 0; i--) begin
      if (mag13[i]) begin
        clz = 4'd12 - 4'(i);
        break;
      end
    end
    p = 4'd12 - clz;

    // MSB が bit23 へ来るよう左寄せ。下位は 0 埋めなので厳密。
    signif_o = 24'({mag13, 11'd0} << clz);
    exp_o    = $signed({7'd0, p}) + 11'sd127 + IEXP_W'(scaled_exp_i);
  end

endmodule
