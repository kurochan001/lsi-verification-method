// -----------------------------------------------------------------------------
// e2m1_quantize
//   FP32 の相対指数 e_rel と仮数 frac から E2M1 の大きさ 3bit (E[1:0], M) を
//   決める。roundTiesToEven。仕様書 7.2 / 7.3 節
//
//   [仕様書 7.3 節からの修正 — 丸め結果の割り当て]
//     骨格コードは各 binade で `up ? x.5 : x.0` と 2 択にしていたが、これは
//     7.2 節の確定表と一致しない。E2M1 の仮数は 1bit なので、正しくは
//       up    = g & (s | m1)      … m1 を仮数 LSB とみなした RNE の増分
//       rm1   = m1 ^ up           … 丸め後の仮数ビット
//       carry = m1 & up           … 次の binade への繰り上がり
//     である。骨格コードでは例えば v = 1.5 (m1=1, g=0) が 1.0 に、
//     v = 1.75 (タイ) が 1.5 になり、7.2 節の区間表 [1.75, 2.5] -> 2.0 を
//     満たさない。本実装は 7.2 節の確定表を規範として実装した。
//
//     e_rel = -1 (v ∈ [0.5, 1)) だけは扱いが異なる。この区間の E2M1 代表点は
//     0.5 のみで、0.75 は表現できない。丸め先は 0.5 か 1.0、中点 0.75 の
//     タイは偶数仮数側 (1.0, M=0) へ入るので、判定は m1 単独になる。
//
//   非負 scaled 値 v の量子化区間 (仕様書 7.2 節。[ ] はタイが当該コード側):
//     [0, 0.25]     -> 000 (0)
//     (0.25, 0.75)  -> 001 (0.5)
//     [0.75, 1.25]  -> 010 (1.0)
//     (1.25, 1.75)  -> 011 (1.5)
//     [1.75, 2.5]   -> 100 (2.0)
//     (2.5, 3.5)    -> 101 (3.0)
//     [3.5, 5.0]    -> 110 (4.0)
//     (5.0, +inf)   -> 111 (6.0 クランプ)
// -----------------------------------------------------------------------------
module e2m1_quantize
  import mxfp4_pkg::*;
(
  input  logic signed [SCALED_EXP_W-1:0] e_rel_i,     // v の実指数 (exp_field - X_biased)
  input  logic [22:0]                    frac_i,      // v の仮数 23bit
  input  logic                           is_zero_i,   // v がゼロ / デノーマル (DAZ)
  output logic [2:0]                     mag3_o       // E2M1 の {E[1:0], M}
);

  logic m1, g, s, up, rm1, carry;

  always_comb begin
    m1    = frac_i[22];          // E2M1 仮数 1bit に対応 (x.5 か否か)
    g     = frac_i[21];          // guard
    s     = |frac_i[20:0];       // sticky
    up    = g & (s | m1);        // RNE の増分
    rm1   = m1 ^ up;             // 丸め後の仮数ビット
    carry = m1 & up;             // 次の binade へ繰り上がり

    if (is_zero_i) begin
      mag3_o = 3'b000;
    end else begin
      unique case (1'b1)
        // v < 0.25
        (e_rel_i <= -$signed(SCALED_EXP_W'(3))): mag3_o = 3'b000;
        // [0.25, 0.5): 0.25 ちょうど (m1=g=s=0) はタイで 0 へ、それ以外は 0.5
        (e_rel_i == -$signed(SCALED_EXP_W'(2))): mag3_o = (m1 | g | s) ? 3'b001 : 3'b000;
        // [0.5, 1): 0.5 or 1.0。中点 0.75 のタイは偶数側 1.0 へ
        (e_rel_i == -$signed(SCALED_EXP_W'(1))): mag3_o = m1 ? 3'b010 : 3'b001;
        // [1, 2): 1.0 or 1.5、繰り上がりは 2.0
        (e_rel_i ==  $signed(SCALED_EXP_W'(0))): mag3_o = carry ? 3'b100 : {2'b01, rm1};
        // [2, 4): 2.0 or 3.0、繰り上がりは 4.0
        (e_rel_i ==  $signed(SCALED_EXP_W'(1))): mag3_o = carry ? 3'b110 : {2'b10, rm1};
        // [4, 8): 4.0 or 6.0。繰り上がり先 8.0 は表現できないので 6.0 へクランプ
        (e_rel_i ==  $signed(SCALED_EXP_W'(2))): mag3_o = carry ? 3'b111 : {2'b11, rm1};
        // v >= 8 -> 6.0 へクランプ
        default:                                 mag3_o = 3'b111;
      endcase
    end
  end

endmodule
