// -----------------------------------------------------------------------------
// elem_mul
//   dec2 同士の要素積。(a x 2)(b x 2) = 4 (a b) なので実値の 4 倍が得られる。
//   仕様書 4.3 節
// -----------------------------------------------------------------------------
module elem_mul
  import mxfp4_pkg::*;
(
  input  logic signed [DEC2_W-1:0]  a2_i,      // -12..+12
  input  logic signed [DEC2_W-1:0]  b2_i,      // -12..+12
  output logic signed [PROD4_W-1:0] prod4_o    // -144..+144
);

  assign prod4_o = a2_i * b2_i;

endmodule
