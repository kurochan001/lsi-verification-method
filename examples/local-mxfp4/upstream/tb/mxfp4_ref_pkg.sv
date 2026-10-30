// -----------------------------------------------------------------------------
// mxfp4_ref_pkg
//   リファレンスモデル (テストベンチ専用。合成対象外)。
//   仕様書 6.5 節 / 9.2 節
//
//   照合戦略は 2 層 (仕様書 9.2 節):
//     ブロック内 : dec2 デコードと 32 項整数和は RTL と完全一致するはずなので
//                  整数で組んで SoP4 をビット照合する。
//     ブロック間 : 各累積ステップに FP32 丸め (RNE) + FTZ + ±Inf 飽和を適用し
//                  最終 32bit をビット照合する。
//
//   [仕様書 6.5 節からの強化 — 二重丸めの排除]
//     6.5 節の方針 2 は double で累積してから FP32 へ丸めるが、指数差が大きい
//     ケースでは double 側の丸めが先に効き、FP32 の GRS 判定と食い違い得る
//     (二重丸め)。本モジュールは acc と項を共通指数の広幅整数へ展開して
//     厳密に加算し、その結果を 1 回だけ RNE で FP32 へ丸める。
//     RTL の 28bit GRS パス (アライン量 26 で飽和) とは独立な実装なので、
//     飽和シフトの正しさ自体も検証対象にできる。
// -----------------------------------------------------------------------------
package mxfp4_ref_pkg;

  localparam int RW      = 128;  // 厳密加算の作業幅
  localparam int MAX_SH  = 96;   // 指数差の上限 (これを超えた分は sticky に潰す)
                                 // 24bit 仮数 + GRS より十分大きいので結果は厳密

  localparam logic [31:0] QNAN = 32'h7FC0_0000;

  // ---------------------------------------------------------------------------
  // E2M1 コード -> dec2 (= value x 2)。仕様書 2.1 節の表。
  // ---------------------------------------------------------------------------
  function automatic int dec2_of(input logic [3:0] code);
    int mag;
    unique case (code[2:0])
      3'b000: mag = 0;
      3'b001: mag = 1;
      3'b010: mag = 2;
      3'b011: mag = 3;
      3'b100: mag = 4;
      3'b101: mag = 6;
      3'b110: mag = 8;
      3'b111: mag = 12;
    endcase
    return code[3] ? -mag : mag;
  endfunction

  // E2M1 コード -> 実数値
  function automatic real e2m1_to_real(input logic [3:0] code);
    return real'(dec2_of(code)) / 2.0;
  endfunction

  // ---------------------------------------------------------------------------
  // 1 ブロックペアの厳密 SoP4 (= 4 x Σ Pa Pb)。仕様書 9.2 節。
  //   ブロック配置は 2.3 節の {scale[7:0], elems[127:0]}。
  // ---------------------------------------------------------------------------
  function automatic int ref_sop4(input logic [135:0] a, input logic [135:0] b);
    int s;
    s = 0;
    for (int i = 0; i < 32; i++)
      s += dec2_of(a[4*i +: 4]) * dec2_of(b[4*i +: 4]);
    return s;
  endfunction

  // ---------------------------------------------------------------------------
  // 広幅整数 M x 2^e_min を FP32 へ 1 回だけ RNE で丸めて格納する。
  //   gradual = 0: アンダーフローは FTZ (仕様書 6.3 節の規約)。
  //   gradual = 1: デノーマル出力 (6.3 節の発展課題)。値を 2^-149 単位の整数へ
  //                RNE で丸めるだけでよい。結果 q は 24bit に収まり、
  //                q = 2^23 がちょうど正規最小 (指数フィールド 1) を表すので、
  //                {sign, 7'd0, q} と並べればデノーマル / 正規の境界が繋がる。
  //   M != 0 であること。
  // ---------------------------------------------------------------------------
  function automatic logic [31:0] ref_round_pack(input logic          sign,
                                                 input logic [RW-1:0] M,
                                                 input int            e_min,
                                                 input bit            gradual);
    int            p, ef, sh;
    logic [RW-1:0] Mn, Q, maskd;
    logic [23:0]   frac24;
    logic [24:0]   frac_c;
    logic          g, rest, lsb, up;

    // 正規化: MSB 位置 p。値 = M x 2^e_min = 1.f x 2^(p + e_min)
    p = 0;
    for (int i = RW-1; i >= 0; i--) begin
      if (M[i]) begin
        p = i;
        break;
      end
    end
    ef = p + e_min + 127;

    if (ef <= 0 && gradual) begin
      sh = -(e_min + 149);
      if (sh <= 0) begin
        Q = M << (-sh);                       // 厳密 (ef <= 0 なので 24bit に収まる)
      end else if (sh >= RW) begin
        Q = '0;
      end else begin
        maskd = (sh >= 2) ? ~({RW{1'b1}} << (sh-1)) : '0;
        g     = M[sh-1];
        rest  = (sh >= 2) ? |(M & maskd) : 1'b0;
        Q     = M >> sh;
        lsb   = Q[0];
        up    = g & (rest | lsb);
        Q     = Q + RW'(up);
      end
      return {sign, 7'd0, Q[23:0]};
    end

    Mn     = M << (RW-1 - p);
    frac24 = Mn[RW-1 -: 24];
    g      = Mn[RW-1-24];
    rest   = |Mn[RW-1-25 : 0];

    // RNE
    lsb    = frac24[0];
    up     = g & (rest | lsb);
    frac_c = {1'b0, frac24} + {24'd0, up};
    if (frac_c[24]) begin
      ef     = ef + 1;
      frac_c = frac_c >> 1;
    end

    if (ef >= 255) return {sign, 8'hFF, 23'd0};   // オーバーフロー -> ±Inf (6.2 節)
    if (ef <= 0)   return {sign, 31'd0};          // アンダーフロー -> FTZ ±0 (6.3 節)
    return {sign, ef[7:0], frac_c[22:0]};
  endfunction

  // ---------------------------------------------------------------------------
  // acc_in + sop4 x 2^scaled_exp を厳密に計算し、FP32 へ RNE + FTZ + Inf 飽和。
  //   仕様書 6.2 / 6.3 / 6.4 節の規約に従う。
  //   gradual = 1 では 6.3 節の発展課題モードになり、acc 側のデノーマルも
  //   値として扱う (DAZ を適用しない。適用すると累積が壊れる)。
  // ---------------------------------------------------------------------------
  function automatic logic [31:0] ref_fp32_add_term_ex(
      input logic [31:0] acc_in,
      input int          sop4,
      input int          scaled_exp,
      input bit          gradual);

    logic        sa, st;
    logic [7:0]  ea;
    logic [23:0] ma;
    int          mt;
    int          ea_e, et_e, e_min, d;
    logic [RW-1:0] A, T, M;
    logic        res_sign;
    logic        acc_zero, acc_nan, acc_inf, acc_denorm, term_zero;

    sa = acc_in[31];
    ea = acc_in[30:23];

    acc_nan    = (ea == 8'hFF) && (acc_in[22:0] != 23'd0);
    acc_inf    = (ea == 8'hFF) && (acc_in[22:0] == 23'd0);
    acc_denorm = gradual && (ea == 8'h00) && (acc_in[22:0] != 23'd0);
    acc_zero   = gradual ? (acc_in[30:0] == 31'd0)   // gradual: デノーマルは値
                         : (ea == 8'h00);            // FTZ: DAZ (6.4 節)
    ma         = {~acc_denorm, acc_in[22:0]};
    term_zero  = (sop4 == 0);

    if (acc_nan) return QNAN;
    if (acc_inf) return acc_in;             // Inf + 有限 = Inf (6.2 節)
    if (term_zero && acc_zero) return 32'h0000_0000;
    if (term_zero) return acc_in;           // acc がデノーマルなら上の分岐で処理済み

    st = (sop4 < 0);
    mt = (sop4 < 0) ? -sop4 : sop4;

    // 各項の「最下位ビットの重み」指数
    //   acc  : ma x 2^(ea - 127 - 23)。デノーマルは指数フィールド 1 と同じ重み
    //   term : mt x 2^scaled_exp
    ea_e = acc_denorm ? (1 - 150) : (int'(ea) - 150);
    et_e = scaled_exp;

    if (acc_zero) begin
      // acc = 0: 項をそのまま正規化する
      A        = '0;
      T        = RW'(mt);
      e_min    = et_e;
      M        = T;
      res_sign = st;
    end else begin
      if (ea_e >= et_e) begin
        d = ea_e - et_e;
        if (d > MAX_SH) begin
          // 項が極小: 厳密和の下位に非ゼロが残るので sticky 相当の 1 で代用
          A     = RW'(ma) << MAX_SH;
          T     = RW'(1);
          e_min = ea_e - MAX_SH;
        end else begin
          A     = RW'(ma) << d;
          T     = RW'(mt);
          e_min = et_e;
        end
      end else begin
        d = et_e - ea_e;
        if (d > MAX_SH) begin
          T     = RW'(mt) << MAX_SH;
          A     = RW'(1);
          e_min = et_e - MAX_SH;
        end else begin
          T     = RW'(mt) << d;
          A     = RW'(ma);
          e_min = ea_e;
        end
      end

      if (sa == st) begin
        M        = A + T;
        res_sign = sa;
      end else if (A >= T) begin
        M        = A - T;
        res_sign = sa;
      end else begin
        M        = T - A;
        res_sign = st;
      end
    end

    if (M == '0) return 32'h0000_0000;      // 完全相殺 -> +0 (RNE の規定)
    return ref_round_pack(res_sign, M, e_min, gradual);
  endfunction

  // FTZ 版 (仕様書 6.3 節の既定)。既存の呼び出し互換。
  function automatic logic [31:0] ref_fp32_add_term(
      input logic [31:0] acc_in,
      input int          sop4,
      input int          scaled_exp);
    return ref_fp32_add_term_ex(acc_in, sop4, scaled_exp, 1'b0);
  endfunction

  // ---------------------------------------------------------------------------
  // 任意の FP32 同士の厳密加算 -> RNE + FTZ + Inf 飽和。
  //   mxfp4_fp32_add_core を汎用 FP32 加算器として単体検証するための基準器。
  //   BDP 経由 (ref_fp32_add_term) では第 2 項が i2f 由来の 13bit 仮数に限られ、
  //   桁上げ時の sticky が丸めに効く条件を踏みにくいため、両オペランドが任意の
  //   FP32 を取れる形を用意する。
  //   Inf / NaN は呼び出し側で除外すること。
  // ---------------------------------------------------------------------------
  function automatic logic [31:0] ref_fp32_add_fp32_ex(input logic [31:0] x,
                                                       input logic [31:0] y,
                                                       input bit          gradual);
    logic          sx, sy, res_sign, dx, dy;
    logic [7:0]    ex, ey;
    logic [23:0]   mx, my;
    int            ex_e, ey_e, e_min, d;
    logic [RW-1:0] magnitude_x, magnitude_y, M;

    sx = x[31];  ex = x[30:23];
    sy = y[31];  ey = y[30:23];

    // gradual = 1 ではデノーマルを値として扱う (暗黙ビット 0、指数フィールド 1 相当)。
    dx = gradual && (ex == 8'h00) && (x[22:0] != 23'd0);
    dy = gradual && (ey == 8'h00) && (y[22:0] != 23'd0);
    mx = {~dx, x[22:0]};
    my = {~dy, y[22:0]};

    // ゼロ (gradual = 0 では DAZ によりデノーマルも含む。仕様書 6.4 節)
    if (gradual) begin
      if (x[30:0] == 31'd0 && y[30:0] == 31'd0) return 32'h0000_0000;
      if (x[30:0] == 31'd0) return y;
      if (y[30:0] == 31'd0) return x;
    end else begin
      if (ex == 8'h00 && ey == 8'h00) return 32'h0000_0000;
      if (ex == 8'h00) return y;
      if (ey == 8'h00) return x;
    end

    ex_e = dx ? (1 - 150) : (int'(ex) - 150);   // mx x 2^(ex - 127 - 23)
    ey_e = dy ? (1 - 150) : (int'(ey) - 150);

    if (ex_e >= ey_e) begin
      d = ex_e - ey_e;
      if (d > MAX_SH) begin
        magnitude_x = RW'(mx) << MAX_SH;  magnitude_y = RW'(1);  e_min = ex_e - MAX_SH;
      end else begin
        magnitude_x = RW'(mx) << d;       magnitude_y = RW'(my); e_min = ey_e;
      end
    end else begin
      d = ey_e - ex_e;
      if (d > MAX_SH) begin
        magnitude_y = RW'(my) << MAX_SH;  magnitude_x = RW'(1);  e_min = ey_e - MAX_SH;
      end else begin
        magnitude_y = RW'(my) << d;       magnitude_x = RW'(mx); e_min = ex_e;
      end
    end

    if (sx == sy) begin
      M        = magnitude_x + magnitude_y;
      res_sign = sx;
    end else if (magnitude_x >= magnitude_y) begin
      M        = magnitude_x - magnitude_y;
      res_sign = sx;
    end else begin
      M        = magnitude_y - magnitude_x;
      res_sign = sy;
    end

    if (M == '0) return 32'h0000_0000;
    return ref_round_pack(res_sign, M, e_min, gradual);
  endfunction

  // FTZ / DAZ 版 (仕様書 6.3 / 6.4 節の既定)。既存の呼び出し互換。
  function automatic logic [31:0] ref_fp32_add_fp32(input logic [31:0] x, input logic [31:0] y);
    return ref_fp32_add_fp32_ex(x, y, 1'b0);
  endfunction

  // ---------------------------------------------------------------------------
  // ブロック列の累積リファレンス。仕様書 4.1 節の演算順序 (ブロック昇順) を厳守。
  // ---------------------------------------------------------------------------
  function automatic logic [31:0] ref_dot_series_ex(
      input logic [135:0] a_blk [],
      input logic [135:0] b_blk [],
      input bit           gradual);
    logic [31:0] acc32;
    int sop4, sexp;
    acc32 = 32'h0000_0000;
    foreach (a_blk[j]) begin
      // スケール NaN はブロック単位で NaN 伝播 (仕様書 2.4 節)
      if (a_blk[j][135:128] == 8'hFF || b_blk[j][135:128] == 8'hFF)
        return QNAN;
      sop4  = ref_sop4(a_blk[j], b_blk[j]);
      sexp  = int'(a_blk[j][135:128]) + int'(b_blk[j][135:128]) - 256;
      acc32 = ref_fp32_add_term_ex(acc32, sop4, sexp, gradual);
    end
    return acc32;
  endfunction

  // FTZ 版 (仕様書 6.3 節の既定)。既存の呼び出し互換。
  function automatic logic [31:0] ref_dot_series(
      input logic [135:0] a_blk [],
      input logic [135:0] b_blk []);
    return ref_dot_series_ex(a_blk, b_blk, 1'b0);
  endfunction

  // ---------------------------------------------------------------------------
  // 量子化リファレンス。仕様書 7.2 節の確定表を実数比較でそのまま実装する
  // (RTL の相対指数 + M1/G/S 方式とは独立)。
  //   [0, 0.25] 000 / (0.25, 0.75) 001 / [0.75, 1.25] 010 / (1.25, 1.75) 011 /
  //   [1.75, 2.5] 100 / (2.5, 3.5) 101 / [3.5, 5.0] 110 / (5.0, inf) 111
  // ---------------------------------------------------------------------------
  function automatic logic [2:0] ref_quantize_e2m1(input real v);
    if (v <= 0.25) return 3'b000;
    if (v <  0.75) return 3'b001;
    if (v <= 1.25) return 3'b010;
    if (v <  1.75) return 3'b011;
    if (v <= 2.5)  return 3'b100;
    if (v <  3.5)  return 3'b101;
    if (v <= 5.0)  return 3'b110;
    return 3'b111;
  endfunction

  // FP32 ビットパターン -> real (DAZ 適用。Inf/NaN は呼び出し側で除外すること)
  function automatic real fp32_to_real(input logic [31:0] f);
    real m;
    int  e;
    if (f[30:23] == 8'h00) return 0.0;             // DAZ
    m = 1.0 + real'(f[22:0]) / 8388608.0;
    e = int'(f[30:23]) - 127;
    return (f[31] ? -m : m) * (2.0 ** e);
  endfunction

  // ---------------------------------------------------------------------------
  // ブロック量子化リファレンス。仕様書 7.1 / 7.4 / 7.5 節。
  //   use34 = 1 で 7.7 節の 3/4 スケーリング変形 (shared_exp は Algorithm 1 の
  //   まま。要素だけを 3/4 倍してから量子化する)。0.75 は 2 進で厳密、
  //   24bit 仮数 x 3 も 26bit で double に収まるので、この乗算に丸めはない。
  // ---------------------------------------------------------------------------
  function automatic logic [135:0] ref_encode_block_ex(input logic [31:0] v [32],
                                                       input bit use34);
    logic [30:0] key [32];
    logic [30:0] amax;
    logic [7:0]  amax_exp, xb;
    logic        special;
    logic [127:0] elems;
    real         scaled;
    logic [2:0]  mag3;
    int          ex;

    special = 1'b0;
    amax    = 31'd0;
    for (int i = 0; i < 32; i++) begin
      if (v[i][30:23] == 8'hFF) special = 1'b1;
      key[i] = (v[i][30:23] == 8'h00) ? 31'd0 : v[i][30:0];   // DAZ
      if (key[i] > amax) amax = key[i];
    end

    if (special) return {8'hFF, 128'd0};          // ブロック単位 NaN (7.5 節)
    if (amax == 31'd0) return {8'h00, 128'd0};    // 全ゼロブロック (7.5 節)

    amax_exp = amax[30:23];
    xb       = (amax_exp <= 8'd2) ? 8'd0 : (amax_exp - 8'd2);

    elems = 128'd0;
    for (int i = 0; i < 32; i++) begin
      if (v[i][30:23] == 8'h00) begin
        mag3 = 3'b000;                            // DAZ
      end else begin
        // scaled = |v| / 2^(xb - 127)。指数減算なので double で厳密。
        ex     = 127 - int'(xb);
        scaled = fp32_to_real({1'b0, v[i][30:0]}) * (2.0 ** ex);
        if (use34) scaled = scaled * 0.75;
        mag3   = ref_quantize_e2m1(scaled);
      end
      elems[4*i +: 4] = {v[i][31], mag3};
    end
    return {xb, elems};
  endfunction

  // Algorithm 1 (仕様書 7.1 節) 版。既存の呼び出し互換。
  function automatic logic [135:0] ref_encode_block(input logic [31:0] v [32]);
    return ref_encode_block_ex(v, 1'b0);
  endfunction

  // ---------------------------------------------------------------------------
  // ブロックのデコード (量子化誤差の測定用。仕様書 2.4 節の解釈)。
  //   要素 i の値 = sign x mag(E2M1) x 2^(X_biased - 127)
  // ---------------------------------------------------------------------------
  function automatic real ref_decode_elem(input logic [135:0] blk, input int i);
    logic [7:0] xb;
    int         ex;
    xb = blk[135:128];
    if (xb == 8'hFF) return 0.0;                  // NaN ブロックは対象外
    ex = int'(xb) - 127;
    return e2m1_to_real(blk[4*i +: 4]) * (2.0 ** ex);
  endfunction

endpackage
