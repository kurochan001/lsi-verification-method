// -----------------------------------------------------------------------------
// e2m1_decode
//   E2M1 (4bit) -> dec2 (= value x 2 の整数, -12..+12)
//   仕様書 4.2 節
//
//   E2M1 の表現値はすべて 0.5 刻みなので、2 倍して整数化すると
//   乗算器を整数演算に落とせる。
// -----------------------------------------------------------------------------
module e2m1_decode
  import mxfp4_pkg::*;
(
  input  logic [3:0]              code_i,     // {S, E[1:0], M}
  output logic signed [DEC2_W-1:0] dec2_o,    // value x 2
  output logic                    is_zero_o   // ±0 判定
);

  logic [3:0] mag2;

  always_comb begin
    mag2      = e2m1_mag2(code_i[2:0]);
    is_zero_o = (mag2 == 4'd0);
    // 符号で 2 の補数化。mag2 は最大 12 なので signed 6bit に収まる。
    dec2_o    = code_i[3] ? -$signed({2'b00, mag2}) : $signed({2'b00, mag2});
  end

endmodule
