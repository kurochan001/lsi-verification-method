// -----------------------------------------------------------------------------
// mxfp4_fp32_add_nearfar
//   near/far 二経路の FP32 加算器コア。組合せ回路。仕様書 5.7 節の発展課題。
//   mxfp4_fp32_add_core (統合パス) と全出力がビット一致する代替実装である
//   (仕様書 12 章 注意 7: 最適化版は統合パス版とのビット一致回帰を必ず維持する)。
//
//   経路の分け方:
//     near : 実効減算 かつ 指数差 <= 1
//            アラインは 0/1bit で済むが、桁落ちが最大幅まで起き得るので
//            正規化に大きな左シフトが要る -> LZA + 1bit 補正。
//     far  : それ以外 (実効加算、または指数差 >= 2)
//            アラインに大きな右シフトが要るが、正規化は高々 1bit で済む。
//              - 実効加算    : 桁上げで右 1bit
//              - 実効減算    : sig_l_ext >= 2^26、aligned_s <= 2^25 なので
//                              sum >= 2^25、すなわち左 1bit まで
//
//   統合パスが「大きな右シフト」と「大きな左シフト」を直列に持つのに対し、
//   こちらはどちらの経路も片方だけになる。これが 5.7 節の言う遅延最適化。
//
//   丸めと gradual underflow の段は統合パスと同じ規約で書いてあるが、
//   共通モジュールに切り出さず意図的に独立実装にしてある。同じソースを
//   共有すると「両者が同じように間違っている」場合にビット一致回帰が
//   素通りしてしまうため。
// -----------------------------------------------------------------------------
module mxfp4_fp32_add_nearfar
  import mxfp4_pkg::*;
#(
  parameter bit GRADUAL_UF = 1'b0    // 1: デノーマル出力 (仕様書 6.3 節)
) (
  input  logic                     a_sign,
  input  logic signed [IEXP_W-1:0] a_exp,
  input  logic [SIGNIF_W-1:0]      a_sig,     // 暗黙 1 込み (正規化済みであること)
  input  logic                     b_sign,
  input  logic signed [IEXP_W-1:0] b_exp,
  input  logic [SIGNIF_W-1:0]      b_sig,
  output logic                     r_sign,
  output logic signed [IEXP_W-1:0] r_exp,
  output logic [SIGNIF_W-1:0]      r_sig,
  output logic                     r_carry_ovf,
  output logic                     r_zero,
  // 観測ポート (合成時は削除可)
  output logic                     near_dbg,      // near path を選んだ
  output logic [4:0]               lza_err_dbg    // LZA の予測誤差 (0 か 1)
);

  // ===========================================================================
  // 共通: 指数比較で large / small を決める
  // ===========================================================================
  logic                     a_ge, eff_sub, is_near;
  logic signed [IEXP_W-1:0] exp_l, exp_diff;
  logic                     s_l, s_s;
  logic [SIGNIF_W-1:0]      sig_l, sig_s;
  logic [ALIGN_W-1:0]       ext_s, sig_l_ext;

  always_comb begin
    a_ge     = (a_exp > b_exp) || ((a_exp == b_exp) && (a_sig >= b_sig));
    exp_l    = a_ge ? a_exp : b_exp;
    exp_diff = a_ge ? (a_exp - b_exp) : (b_exp - a_exp);
    s_l      = a_ge ? a_sign : b_sign;
    s_s      = a_ge ? b_sign : a_sign;
    sig_l    = a_ge ? a_sig  : b_sig;
    sig_s    = a_ge ? b_sig  : a_sig;
    eff_sub  = s_l ^ s_s;
    is_near  = eff_sub && (exp_diff <= $signed(IEXP_W'(1)));

    ext_s     = {1'b0, sig_s, 3'b000};
    sig_l_ext = {1'b0, sig_l, 3'b000};
  end

  assign near_dbg = is_near;

  // ===========================================================================
  // far path: 大きなアライン + 高々 1bit の正規化
  // ===========================================================================
  logic [5:0]         sh_f;
  logic [ALIGN_W-1:0] shifted_f, mask_f, aligned_f, sum_f, norm_f;
  logic               sticky_f;
  logic signed [IEXP_W-1:0] exp_f;

  always_comb begin
    sh_f      = (exp_diff > $signed(IEXP_W'(26))) ? 6'd26 : exp_diff[5:0];
    shifted_f = ext_s >> sh_f;
    mask_f    = ~({ALIGN_W{1'b1}} << sh_f);
    sticky_f  = |(ext_s & mask_f);
    aligned_f = {shifted_f[ALIGN_W-1:1], shifted_f[0] | sticky_f};
    sum_f     = eff_sub ? (sig_l_ext - aligned_f) : (sig_l_ext + aligned_f);

    norm_f = sum_f;
    exp_f  = exp_l;
    if (sum_f == '0) begin
      norm_f = '0;
    end else if (sum_f[ALIGN_W-1]) begin
      // 桁上げ: 右 1bit。押し出しビットは sticky へ OR。
      norm_f    = sum_f >> 1;
      norm_f[0] = norm_f[0] | sum_f[0];
      exp_f     = exp_l + 11'sd1;
    end else if (!sum_f[ALIGN_W-2]) begin
      // 実効減算での 1bit 借り (far path では 1bit を超えない)
      norm_f = sum_f << 1;
      exp_f  = exp_l - 11'sd1;
    end
  end

  // ===========================================================================
  // near path: アラインは 0/1bit、正規化は LZA + 1bit 補正
  //   ext_s の下位 3bit は 0 なので、1bit 右シフトで押し出されるビットはなく
  //   sticky は発生しない (アラインは厳密)。
  // ===========================================================================
  logic [ALIGN_W-1:0] aligned_n, sum_n, shifted_n, norm_n;
  logic [4:0]         nlz_pred, nlz_n;
  logic signed [IEXP_W-1:0] exp_n_near;

  assign aligned_n = (exp_diff == $signed(IEXP_W'(1))) ? (ext_s >> 1) : ext_s;
  assign sum_n     = sig_l_ext - aligned_n;

  mxfp4_lza u_lza (
    .a_i        (sig_l_ext),
    .b_i        (aligned_n),
    .nlz_pred_o (nlz_pred)
  );

  always_comb begin
    shifted_n = sum_n << nlz_pred;
    if (sum_n == '0) begin
      // 完全相殺。呼び出し側が r_zero を見て +0 を格納する。
      norm_n     = '0;
      nlz_n      = 5'd0;
      exp_n_near = exp_l;
    end else if (shifted_n[ALIGN_W-2]) begin
      norm_n     = shifted_n;
      nlz_n      = nlz_pred;
      exp_n_near = exp_l - $signed({6'd0, nlz_pred});
    end else begin
      // LZA の予測が 1bit 手前だった場合の補正
      norm_n     = shifted_n << 1;
      nlz_n      = nlz_pred + 5'd1;
      exp_n_near = exp_l - $signed({6'd0, nlz_pred}) - 11'sd1;
    end
  end

  // LZA の予測誤差 (0 か 1 のはず。tb_nearfar が検査する)。
  // 完全相殺では f が全ゼロで nlz_pred が最大値になるが、正規化自体を
  // バイパスするので誤差の概念がない。0 を報告する。
  assign lza_err_dbg = (sum_n == '0) ? 5'd0 : (nlz_n - nlz_pred);

  // ===========================================================================
  // 経路選択 -> gradual underflow -> RNE 丸め
  //   ここから先は統合パスと同じ規約 (仕様書 5.3 / 6.3 節)。
  // ===========================================================================
  always_comb begin
    logic [ALIGN_W-1:0] norm, shifted_d, mask_d;
    logic signed [IEXP_W-1:0] exp_n;
    logic [5:0]         shd;
    logic               g, rnd, stk, lsb, round_up, is_zero;
    logic [SIGNIF_W:0]  rounded;

    norm    = is_near ? norm_n     : norm_f;
    exp_n   = is_near ? exp_n_near : exp_f;
    is_zero = is_near ? (sum_n == '0) : (sum_f == '0);

    // ---- gradual underflow (丸めの前に行う。仕様書 6.3 節) ----
    shd       = 6'd0;
    shifted_d = '0;
    mask_d    = '0;
    if (GRADUAL_UF && !is_zero && (exp_n <= $signed(IEXP_W'(0)))) begin
      shd       = ((11'sd1 - exp_n) > $signed(IEXP_W'(ALIGN_W))) ? 6'(ALIGN_W)
                                                                 : 6'(11'sd1 - exp_n);
      shifted_d = norm >> shd;
      mask_d    = ~({ALIGN_W{1'b1}} << shd);
      norm      = {shifted_d[ALIGN_W-1:1], shifted_d[0] | (|(norm & mask_d))};
      exp_n     = 11'sd1;
    end

    // ---- RNE 丸め ----
    lsb      = norm[3];
    g        = norm[2];
    rnd      = norm[1];
    stk      = norm[0];
    round_up = g & (rnd | stk | lsb);

    rounded = {1'b0, norm[ALIGN_W-2:3]} + {{SIGNIF_W{1'b0}}, round_up};

    if (rounded[SIGNIF_W]) begin
      r_sig       = rounded[SIGNIF_W:1];
      r_exp       = exp_n + 11'sd1;
      r_carry_ovf = 1'b1;
    end else begin
      r_sig       = rounded[SIGNIF_W-1:0];
      r_exp       = exp_n;
      r_carry_ovf = 1'b0;
    end

    r_sign = s_l;
    r_zero = is_zero;
  end

endmodule
