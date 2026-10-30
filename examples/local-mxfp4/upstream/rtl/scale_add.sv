// -----------------------------------------------------------------------------
// scale_add
//   E8M0 スケールの指数合成。
//     X(A) X(B) = 2^(sa-127) x 2^(sb-127) = 2^(sa+sb-254)
//   SoP4 は Σ の 4 倍 (2^2) なので、最終値 = SoP4 x 2^(sa+sb-256)。
//   仕様書 4.5 節
// -----------------------------------------------------------------------------
module scale_add
  import mxfp4_pkg::*;
(
  input  e8m0_t                          sa_i,
  input  e8m0_t                          sb_i,
  output logic signed [SCALED_EXP_W-1:0] scaled_exp_o,  // sa + sb - 256
  output logic                           nan_o          // いずれかが 0xFF
);

  logic [8:0] sum9;   // sa + sb (0..510)

  always_comb begin
    sum9         = {1'b0, sa_i} + {1'b0, sb_i};
    scaled_exp_o = $signed({1'b0, sum9}) - $signed(10'sd256);
    nan_o        = (sa_i == E8M0_NAN) || (sb_i == E8M0_NAN);
  end

endmodule
