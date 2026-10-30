// -----------------------------------------------------------------------------
// mxfp4_bdp  (= mxfp4_pe)
//   ブロック内積ユニット。1 ブロックペア (136bit x 2) の内積を求め、
//   FP32 でブロック間累積する。6 段パイプライン (LAT = 6)。
//   仕様書 4 章 / 5 章 / 6 章
//
//   パイプライン (仕様書 3.2 節):
//     S1 mul      : e2m1_decode + elem_mul + scale_add
//     S2 reduce-a : 32 -> 8
//     S3 reduce-b : 8 -> 1 (= SoP4)
//     S4 EX1      : i2f 変換 (int14 + scaled_exp -> 内部拡張 FP32)
//     S5 EX2      : acc とのアライン / 加減算 / 正規化 / RNE 丸め / 範囲判定
//     S6 out      : 出力レジスタ
//
//   [仕様書 5.5 節からの修正 — アキュムレータの RAW ハザード]
//     5.5 節は EX1 で「アンパック + 指数比較 + アライン」まで行うとしているが、
//     その構成では EX1 (投入 +3) で acc を読み、EX2 (投入 +4) で acc を書く
//     ことになり、1 サイクル 1 ブロックの連続投入 (8.4 節) で直前ブロックの
//     累積結果が間に合わない (3 サイクル分の RAW ハザード)。
//     本実装は 5.6 節の骨格コード (加算器全体が 1 つの組合せモジュール) に
//     従い、acc の読み書きを EX2 の 1 サイクルに閉じ込める。これにより
//     LAT = 6 と 1 ブロック/サイクルのスループットを両立できる。
//
//   [ready 拡張 — 仕様書 3.3 節 / 11 章 段階 7]
//     out_ready = 0 で結果を受け取ってもらえない間、パイプライン全体を
//     単純ストールさせる (全段共通のクロックイネーブル en)。
//       stall    = out_valid & ~out_ready
//       in_ready = ~stall
//     ストール中は valid_q / データ段レジスタ / acc_q / result のすべてが
//     保持されるので、投入順と累積順は ready を使わない構成と完全に一致する。
//     out_ready を常時 1 に固定すれば従来と同一の回路になる。
//
//     この構成では in_ready が out_ready へ組合せ依存する。AMBA AXI
//     (§A3.2.1) は「インタフェースの入力から出力への組合せパスを持たない」
//     ことを要求しており、そのままでは AXI 準拠のソースに直結できない。
//     mxfp4_bdp_fifo は入力側 FIFO でこのパスを切る。
//
//   [gradual underflow — 仕様書 6.3 節 / 11 章 段階 7]
//     GRADUAL_UF = 1 にすると FTZ の代わりにデノーマル出力を返す。
//     内部アキュムレータもデノーマルを保持するため、acc 側の DAZ (6.4 節) は
//     このモードでは適用しない (適用すると自分で作ったデノーマルを次の
//     ブロックでゼロに潰してしまい、累積が壊れる)。既定は FTZ。
// -----------------------------------------------------------------------------
module mxfp4_bdp
  import mxfp4_pkg::*;
#(
  parameter bit GRADUAL_UF  = 1'b0,  // 1: デノーマル出力 (仕様書 6.3 節)
  parameter bit USE_NEARFAR = 1'b0   // 1: near/far 二経路 + LZA 版 (5.7 節)
) (
  input  logic                     clk,
  input  logic                     rst_n,
  input  logic                     in_valid,
  output logic                     in_ready,     // ストール中は 0 (仕様書 3.3 節)
  input  logic [BLOCK_W-1:0]       a_block,      // {scale[7:0], elems[127:0]}
  input  logic [BLOCK_W-1:0]       b_block,
  input  logic                     first,        // 内積列の先頭 (acc 初期化)
  input  logic                     last,         // 内積列の末尾 (結果確定)
  output logic                     out_valid,    // last から LAT 後
  input  logic                     out_ready,    // 下流のバックプレッシャ
  output logic [31:0]              result,       // FP32 内積結果
  // 観測ポート (仕様書 4.6 節。9.4 節の covergroup 用。合成時は削除可)
  output logic signed [SOP4_W-1:0] sop4_dbg,         // S3 の SoP4
  output logic                     sop_valid_dbg,    // S3 出力が有効なサイクル
  output logic signed [IEXP_W-1:0] exp_internal_dbg, // S5 の丸め後内部指数
  output logic                     exp_valid_dbg,    // S5 の組合せが有効なサイクル
  output logic                     gradual_uf_dbg    // GRADUAL_UF の値 (SVA 用)
);

  assign gradual_uf_dbg = GRADUAL_UF;

  // ===========================================================================
  // ストール制御 (仕様書 3.3 節)
  // ===========================================================================
  logic stall, en;

  assign stall    = out_valid & ~out_ready;
  assign en       = ~stall;
  assign in_ready = en;

  // ===========================================================================
  // 制御パイプライン
  //   valid_q[n] は「n+1 段目のレジスタに載っているデータが有効か」を示す。
  //   valid_q[LAT-1] が出力レジスタに対応する。
  // ===========================================================================
  logic [LAT-1:0] valid_q, first_q, last_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      valid_q <= '0;
      first_q <= '0;
      last_q  <= '0;
    end else if (en) begin
      valid_q <= {valid_q[LAT-2:0], in_valid};
      first_q <= {first_q[LAT-2:0], first & in_valid};
      last_q  <= {last_q[LAT-2:0],  last  & in_valid};
    end
  end

  // ===========================================================================
  // S1: e2m1_decode + elem_mul + scale_add
  // ===========================================================================
  logic signed [DEC2_W-1:0]  a2    [K];
  logic signed [DEC2_W-1:0]  b2    [K];
  logic signed [PROD4_W-1:0] prod4 [K];

  for (genvar i = 0; i < K; i++) begin : g_elem
    e2m1_decode u_dec_a (
      .code_i   (a_block[4*i +: 4]),
      .dec2_o   (a2[i]),
      .is_zero_o()                    // dec2 = 0 で判定できるため未使用
    );
    e2m1_decode u_dec_b (
      .code_i   (b_block[4*i +: 4]),
      .dec2_o   (b2[i]),
      .is_zero_o()
    );
    elem_mul u_mul (
      .a2_i   (a2[i]),
      .b2_i   (b2[i]),
      .prod4_o(prod4[i])
    );
  end

  logic signed [SCALED_EXP_W-1:0] sexp;
  logic                           nan_sc;

  scale_add u_scale_add (
    .sa_i        (a_block[BLOCK_W-1 -: 8]),
    .sb_i        (b_block[BLOCK_W-1 -: 8]),
    .scaled_exp_o(sexp),
    .nan_o       (nan_sc)
  );

  logic signed [PROD4_W-1:0]      prod4_q [K];
  logic signed [SCALED_EXP_W-1:0] sexp_q1, sexp_q2, sexp_q3;
  logic                           nan_q1,  nan_q2,  nan_q3;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < K; i++) prod4_q[i] <= '0;
      sexp_q1 <= '0; sexp_q2 <= '0; sexp_q3 <= '0;
      nan_q1  <= 1'b0; nan_q2 <= 1'b0; nan_q3 <= 1'b0;
    end else if (en) begin
      for (int i = 0; i < K; i++) prod4_q[i] <= prod4[i];
      // scaled_exp / nan は SoP4 (S3 出力) と揃うよう 3 段遅延させる
      sexp_q1 <= sexp;    nan_q1 <= nan_sc;
      sexp_q2 <= sexp_q1; nan_q2 <= nan_q1;
      sexp_q3 <= sexp_q2; nan_q3 <= nan_q2;
    end
  end

  // ===========================================================================
  // S2 / S3: 32 項整数加算ツリー
  // ===========================================================================
  logic signed [SOP4_W-1:0] sop4;

  reduce_tree u_reduce (
    .clk    (clk),
    .rst_n  (rst_n),
    .en     (en),
    .prod4_i(prod4_q),
    .sop4_o (sop4)
  );

  assign sop4_dbg      = sop4;
  assign sop_valid_dbg = valid_q[2];   // sop4 が有効な段 (S3 出力)
  assign exp_valid_dbg = valid_q[3];   // exp_internal_dbg が有効な段 (S5 組合せ)

  // ===========================================================================
  // S4 (EX1): int14 -> 内部拡張 FP32 変換
  // ===========================================================================
  logic                     t_sign, t_zero, t_nan;
  logic signed [IEXP_W-1:0] t_exp;
  logic [SIGNIF_W-1:0]      t_sig;

  mxfp4_i2f u_i2f (
    .sop4_i      (sop4),
    .scaled_exp_i(sexp_q3),
    .nan_i       (nan_q3),
    .sign_o      (t_sign),
    .exp_o       (t_exp),
    .signif_o    (t_sig),
    .zero_o      (t_zero),
    .nan_o       (t_nan)
  );

  logic                     t_sign_q, t_zero_q, t_nan_q;
  logic signed [IEXP_W-1:0] t_exp_q;
  logic [SIGNIF_W-1:0]      t_sig_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      t_sign_q <= 1'b0; t_zero_q <= 1'b1; t_nan_q <= 1'b0;
      t_exp_q  <= '0;   t_sig_q  <= '0;
    end else if (en) begin
      t_sign_q <= t_sign; t_zero_q <= t_zero; t_nan_q <= t_nan;
      t_exp_q  <= t_exp;  t_sig_q  <= t_sig;
    end
  end

  // ===========================================================================
  // S5 (EX2): FP32 累積
  // ===========================================================================
  logic [31:0] acc_q;
  logic [31:0] acc_eff;      // first のときはゼロ初期化 (仕様書 5.5 節)
  logic [31:0] next_acc;

  logic                     acc_sign, acc_is_zero, acc_is_inf, acc_is_nan, acc_is_denorm;
  logic [4:0]               acc_lz;
  logic [7:0]               acc_expf;
  logic signed [IEXP_W-1:0] acc_exp;
  logic [SIGNIF_W-1:0]      acc_sig;

  always_comb begin
    acc_eff  = first_q[3] ? 32'h0000_0000 : acc_q;
    acc_sign = acc_eff[31];
    acc_expf = acc_eff[30:23];
    acc_is_nan  = (acc_expf == FP32_EXP_MAX) && (acc_eff[22:0] != 23'd0);
    acc_is_inf  = (acc_expf == FP32_EXP_MAX) && (acc_eff[22:0] == 23'd0);

    // FTZ 版: DAZ により指数フィールド 0 (ゼロ / デノーマル) は 0 扱い (6.4 節)。
    // gradual 版: デノーマルも値として扱う。
    acc_is_denorm = GRADUAL_UF && (acc_expf == 8'h00) && (acc_eff[22:0] != 23'd0);
    acc_is_zero   = GRADUAL_UF ? (acc_eff[30:0] == 31'd0) : (acc_expf == 8'h00);

    // acc 仮数 23bit の先頭ゼロ数 (仕様書 5.6 節の LZC と同じ形)
    acc_lz = 5'd22;
    for (int i = 22; i >= 0; i--) begin
      if (acc_eff[i]) begin
        acc_lz = 5'(22 - i);
        break;
      end
    end

    // デノーマルは加算器へ渡す前に正規化する (指数は負まで振れてよい)。
    //   加算器の指数比較は
    //     a_ge = (a_exp > b_exp) || (a_exp == b_exp && a_sig >= b_sig)
    //   で large / small を決めており、これは仮数が [1, 2) に正規化されている
    //   ことを前提にしている。デノーマル (仮数が [0, 1)) をそのまま
    //   exp = 1 で渡すと、i2f 由来の項が exp < 1 を取り得るため
    //   「指数は大きいが絶対値は小さい」オペランドが large 扱いになり、
    //   実効減算で桁借りが起きて結果が壊れる。
    //   値 = sig x 2^(exp-150) は正規化しても不変:
    //     frac x 2^(1-150) = (frac << (lz+1)) x 2^(-lz-150)
    acc_exp = acc_is_denorm ? -IEXP_W'({6'd0, acc_lz})
                            : $signed({3'b000, acc_expf});
    acc_sig = acc_is_denorm ? SIGNIF_W'({1'b0, acc_eff[22:0]} << (acc_lz + 5'd1))
                            : {1'b1, acc_eff[22:0]};
  end

  logic                     add_sign, add_zero;
  logic signed [IEXP_W-1:0] add_exp;
  logic [SIGNIF_W-1:0]      add_sig;

  // 統合パス版と near/far 二経路版はビット一致する (仕様書 12 章 注意 7)。
  // tb_nearfar が加算器単体で、sim-bdp-nf が BDP 全体で回帰を掛ける。
  if (USE_NEARFAR) begin : g_nearfar
    mxfp4_fp32_add_nearfar #(
      .GRADUAL_UF(GRADUAL_UF)
    ) u_add (
      .a_sign(acc_sign),
      .a_exp (acc_exp),
      .a_sig (acc_sig),
      .b_sign(t_sign_q),
      .b_exp (t_exp_q),
      .b_sig (t_sig_q),
      .r_sign     (add_sign),
      .r_exp      (add_exp),
      .r_sig      (add_sig),
      .r_carry_ovf(),          // 痕跡出力。BDP では使用しない
      .r_zero     (add_zero),
      .near_dbg   (),
      .lza_err_dbg()
    );
  end else begin : g_single
    mxfp4_fp32_add_core #(
      .GRADUAL_UF(GRADUAL_UF)
    ) u_add (
      .a_sign(acc_sign),
      .a_exp (acc_exp),
      .a_sig (acc_sig),
      .b_sign(t_sign_q),
      .b_exp (t_exp_q),
      .b_sig (t_sig_q),
      .r_sign     (add_sign),
      .r_exp      (add_exp),
      .r_sig      (add_sig),
      .r_carry_ovf(),
      .r_zero     (add_zero)
    );
  end

  // 内部指数 -> FP32 格納形式。範囲外は 6 章の規約に従う。
  //   加算器の出力を格納する経路。gradual 版では加算器がデノーマル化済み
  //   (exp = 1、暗黙ビット 0) の形で返してくるので、ここでは詰め替えるだけ。
  function automatic logic [31:0] pack_fp32(
      input logic                     sign,
      input logic signed [IEXP_W-1:0] iexp,
      input logic [SIGNIF_W-1:0]      sig);
    if (iexp >= $signed(IEXP_W'(255)))
      pack_fp32 = {sign, FP32_EXP_MAX, 23'd0};   // オーバーフロー: ±Inf 飽和 (6.2 節)
    else if (GRADUAL_UF && !sig[SIGNIF_W-1])
      pack_fp32 = {sign, 8'h00, sig[22:0]};      // デノーマル (6.3 節 発展課題)
    else if (iexp <= $signed(IEXP_W'(0)))
      pack_fp32 = {sign, 31'd0};                 // アンダーフロー: FTZ ±0 (6.3 節)
    else
      pack_fp32 = {sign, iexp[7:0], sig[22:0]};
  endfunction

  // 加算器を通さない厳密値 (i2f 出力そのもの) を格納する経路。
  //   sig より下位のビットは存在しないので、ここでデノーマル化と RNE を
  //   1 回で行っても二重丸めにならない。
  //   丸め結果 q は 24bit で、q = 2^23 のときちょうど正規最小になる。
  //   {sign, 7'd0, q} と並べると指数フィールド 0/1 の境界が自然に繋がる。
  function automatic logic [31:0] pack_fp32_exact(
      input logic                     sign,
      input logic signed [IEXP_W-1:0] iexp,
      input logic [SIGNIF_W-1:0]      sig);
    logic [5:0]          shx;
    logic [4:0]          idx;
    logic [31:0]         sigx, maskx;
    logic                gx, sx, lsbx, upx;
    logic [SIGNIF_W-1:0] qx;
    if (iexp >= $signed(IEXP_W'(255)))
      pack_fp32_exact = {sign, FP32_EXP_MAX, 23'd0};       // ±Inf 飽和 (6.2 節)
    else if (iexp >= $signed(IEXP_W'(1)))
      pack_fp32_exact = {sign, iexp[7:0], sig[22:0]};      // 正規数
    else if (!GRADUAL_UF)
      pack_fp32_exact = {sign, 31'd0};                     // FTZ ±0 (6.3 節)
    else begin
      // シフト量 = 1 - iexp。31 で飽和させれば 24bit 仮数は完全に押し出される。
      shx   = (iexp <= $signed(IEXP_W'(-30))) ? 6'd31 : 6'(11'sd1 - iexp);
      idx   = 5'(shx - 6'd1);          // guard ビットの位置 (shx >= 1)
      sigx  = {8'd0, sig};
      maskx = ~(32'hFFFF_FFFF << idx); // guard より下のビット (sticky)
      gx    = sigx[idx];
      sx    = |(sigx & maskx);
      qx    = SIGNIF_W'(sigx >> shx);
      lsbx  = qx[0];
      upx   = gx & (sx | lsbx);
      pack_fp32_exact = {sign, 7'd0, (qx + {{(SIGNIF_W-1){1'b0}}, upx})};
    end
  endfunction

  always_comb begin
    // ゼロ / NaN / Inf は加算器をバイパスして規約どおりに決める。
    if (t_nan_q || acc_is_nan)        next_acc = FP32_QNAN;
    else if (acc_is_inf)              next_acc = acc_eff;              // Inf + 有限 = Inf
    else if (t_zero_q && acc_is_zero) next_acc = 32'h0000_0000;        // +0
    else if (t_zero_q)                next_acc = acc_eff;
    // acc = 0 のときは加算器を通さず i2f 出力をそのまま格納する。この値は
    // 厳密 (下位ビットなし) なので専用の pack を使う (二重丸め回避)。
    else if (acc_is_zero)             next_acc = pack_fp32_exact(t_sign_q, t_exp_q, t_sig_q);
    else if (add_zero)                next_acc = 32'h0000_0000;        // 完全相殺 -> +0
    else                              next_acc = pack_fp32(add_sign, add_exp, add_sig);

    // カバレッジ観測用: 実際に格納判定へ回った内部指数
    exp_internal_dbg = acc_is_zero ? t_exp_q : add_exp;
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)               acc_q <= 32'h0000_0000;
    else if (en & valid_q[3]) acc_q <= next_acc;
  end

  // ===========================================================================
  // S6: 出力レジスタ
  // ===========================================================================
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)               result <= 32'h0000_0000;
    else if (en & valid_q[4]) result <= acc_q;
  end

  assign out_valid = valid_q[LAT-1] & last_q[LAT-1];

endmodule
