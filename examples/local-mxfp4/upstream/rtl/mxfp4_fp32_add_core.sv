// -----------------------------------------------------------------------------
// mxfp4_fp32_add_core
//   統合パス (single-path) FP32 加算器コア。組合せ回路。
//   指数比較 -> アライン (GRS) -> 実効加減算 -> 正規化 -> RNE 丸め -> 再正規化
//   を単一データパスで直列に流す。仕様書 5.3 / 5.6 節
//
//   [仕様書 5.6 節からの修正]
//     骨格コードは有効仮数を norm[27:4]、G を norm[3] としていたが、
//     ext = {1'b0, sig(24), 3'b000} という 28bit 構成では
//       bit27      = carry
//       bit[26:3]  = 24bit 有効仮数
//       bit2/1/0   = G / R / S
//     が正しい。1bit ずれると丸め判定が常に 1 桁下を見ることになるため修正した。
//
//   ゼロ入力は上位 (mxfp4_bdp) でバイパスする前提。
//
//   [gradual underflow — 仕様書 6.3 節 / 11 章 段階 7]
//     GRADUAL_UF = 1 にすると、丸め後の指数が 1 未満になる場合に指数を 1 へ
//     固定して仮数を右シフトし、デノーマル結果を返す。仕様書 6.3 節が
//     「対応する場合は、指数を 1 に固定して仮数を右シフトし、GRS を維持した
//     まま RNE 丸めする追加パスが要る」と書いているとおり、シフトは丸めの
//     **前** に行う。丸めた後にシフトすると二重丸めになり 1ulp ずれる。
//
//     入力は gradual 版でも従来どおり正規化済み (sig[23] = 1) であること。
//     指数比較 a_ge = (a_exp > b_exp) || (a_exp == b_exp && a_sig >= b_sig) は
//     仮数が [1, 2) にあることを前提にしているので、デノーマル (仮数が [0, 1))
//     をそのまま渡すと「指数は大きいが絶対値は小さい」オペランドが large 扱いに
//     なって結果が壊れる。アキュムレータのデノーマルは mxfp4_bdp 側で
//     正規化してから渡す (内部指数は signed なので負まで振れて構わない)。
//     正規化で exp_n が 1 未満へ落ちても、左シフトは情報を失わないので
//     デノーマル化で元に戻せる。
//
//     GRADUAL_UF = 0 (既定) では下のブロックが丸ごと消え、FTZ 版と完全に
//     同じ回路になる。
// -----------------------------------------------------------------------------
module mxfp4_fp32_add_core
  import mxfp4_pkg::*;
#(
  parameter bit GRADUAL_UF = 1'b0    // 1: デノーマル出力 (仕様書 6.3 節)
) (
  input  logic                     a_sign,
  input  logic signed [IEXP_W-1:0] a_exp,
  input  logic [SIGNIF_W-1:0]      a_sig,     // 暗黙 1 込み
  input  logic                     b_sign,
  input  logic signed [IEXP_W-1:0] b_exp,
  input  logic [SIGNIF_W-1:0]      b_sig,     // 暗黙 1 込み
  output logic                     r_sign,
  output logic signed [IEXP_W-1:0] r_exp,       // 正規化・丸め後の内部指数
  output logic [SIGNIF_W-1:0]      r_sig,       // 暗黙 1 込み
  output logic                     r_carry_ovf, // 丸めオーバーフロー痕跡
  output logic                     r_zero       // 完全相殺 (呼び出し側は +0 を格納)
);

  always_comb begin
    logic                     a_ge;
    logic signed [IEXP_W-1:0] exp_l, exp_diff, exp_n;
    logic                     s_l, s_s;
    logic [SIGNIF_W-1:0]      sig_l, sig_s;
    logic [5:0]               sh;
    logic [ALIGN_W-1:0]       ext_s, shifted, mask, aligned_s, sig_l_ext, sum, norm;
    logic                     sticky, eff_sub;
    logic [4:0]               nlz;
    logic                     g, rnd, stk, lsb, round_up;
    logic [SIGNIF_W:0]        rounded;
    logic [5:0]               shd;
    logic [ALIGN_W-1:0]       shifted_d, mask_d;

    // ---- 指数比較: 大きい方を large、小さい方を small へ ----
    a_ge     = (a_exp > b_exp) || ((a_exp == b_exp) && (a_sig >= b_sig));
    exp_l    = a_ge ? a_exp : b_exp;
    exp_diff = a_ge ? (a_exp - b_exp) : (b_exp - a_exp);
    s_l      = a_ge ? a_sign : b_sign;
    s_s      = a_ge ? b_sign : a_sign;
    sig_l    = a_ge ? a_sig  : b_sig;
    sig_s    = a_ge ? b_sig  : a_sig;

    // ---- アライン右シフト ----
    // シフト量は 26 (= 24 + G + R) で飽和させ、押し出しビットの OR を sticky へ。
    sh        = (exp_diff > $signed(IEXP_W'(26))) ? 6'd26 : exp_diff[5:0];
    ext_s     = {1'b0, sig_s, 3'b000};
    shifted   = ext_s >> sh;
    mask      = ~({ALIGN_W{1'b1}} << sh);
    sticky    = |(ext_s & mask);
    aligned_s = {shifted[ALIGN_W-1:1], shifted[0] | sticky};

    // ---- 実効加減算 ----
    eff_sub   = s_l ^ s_s;
    sig_l_ext = {1'b0, sig_l, 3'b000};
    sum       = eff_sub ? (sig_l_ext - aligned_s) : (sig_l_ext + aligned_s);

    // ---- 正規化 ----
    nlz   = 5'd0;
    norm  = sum;
    exp_n = exp_l;
    if (sum == '0) begin
      // 完全相殺: 正規化をバイパスし +0 を返す (IEEE 754 RNE の規定)
      norm  = '0;
      exp_n = exp_l;
    end else if (sum[ALIGN_W-1]) begin
      // 桁上げ: 右シフト 1 / 指数 +1。押し出しビットは sticky へ OR。
      norm    = sum >> 1;
      norm[0] = norm[0] | sum[0];
      exp_n   = exp_l + 11'sd1;
    end else begin
      // 実効減算で先頭ゼロが出た場合: LZC で左詰め
      for (int i = ALIGN_W-2; i >= 0; i--) begin
        if (sum[i]) begin
          nlz = 5'(ALIGN_W-2 - i);
          break;
        end
      end
      norm  = sum << nlz;
      exp_n = exp_l - $signed({6'd0, nlz});
    end

    // ---- gradual underflow: 指数 1 への揃え直し (仕様書 6.3 節) ----
    // 丸めの前に行うこと。丸めてからシフトすると二重丸めになる。
    shd       = 6'd0;
    shifted_d = '0;
    mask_d    = '0;
    if (GRADUAL_UF && (sum != '0) && (exp_n <= $signed(IEXP_W'(0)))) begin
      // シフト量 = 1 - exp_n。28bit すべて押し出せば結果はゼロなので飽和させる
      // (押し出したビットは sticky に畳み込むので飽和しても丸めは正しい)。
      shd       = ((11'sd1 - exp_n) > $signed(IEXP_W'(ALIGN_W))) ? 6'(ALIGN_W)
                                                                 : 6'(11'sd1 - exp_n);
      shifted_d = norm >> shd;
      mask_d    = ~({ALIGN_W{1'b1}} << shd);
      norm      = {shifted_d[ALIGN_W-1:1], shifted_d[0] | (|(norm & mask_d))};
      exp_n     = 11'sd1;
    end

    // ---- RNE 丸め ----
    // norm[26:3] が 24bit 有効仮数、norm[2]=G, norm[1]=R, norm[0]=S
    lsb      = norm[3];
    g        = norm[2];
    rnd      = norm[1];
    stk      = norm[0];
    round_up = g & (rnd | stk | lsb);

    rounded = {1'b0, norm[ALIGN_W-2:3]} + {{SIGNIF_W{1'b0}}, round_up};

    if (rounded[SIGNIF_W]) begin
      // 丸めで仮数がオーバーフロー (24 -> 25bit): 右シフト 1 / 指数 +1
      r_sig       = rounded[SIGNIF_W:1];
      r_exp       = exp_n + 11'sd1;
      r_carry_ovf = 1'b1;
    end else begin
      r_sig       = rounded[SIGNIF_W-1:0];
      r_exp       = exp_n;
      r_carry_ovf = 1'b0;
    end

    r_sign = s_l;
    r_zero = (sum == '0);
  end

endmodule
