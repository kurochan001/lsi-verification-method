// -----------------------------------------------------------------------------
// quant_encoder
//   FP32 x 32 -> mxfp4_block_t 変換 (量子化エンコーダ)。5 段パイプライン。
//   仕様書 7 章
//
//   stage1   : 絶対値化 (符号除去) + NaN/Inf 検出 + DAZ
//   stage2-3 : amax トーナメント (amax_tree32 内部で 2 段に折り畳み)
//   stage4   : shared_exp / X_biased 計算 + 全ゼロ判定
//   stage5   : 32 並列量子化 (e2m1_quantize) とパック
//
//   スケール決定 (仕様書 7.1 節, Rouhani et al. Algorithm 1):
//     shared_exp = floor(log2(amax)) - emax_elem,  emax_elem = 2 (E2M1 の 6.0 = 2^2 x 1.5)
//     X_biased   = clamp(shared_exp + 127, 0, 254)
//   正規数なら amax の指数フィールドが floor(log2(amax)) + 127 そのものなので
//   X_biased = clamp(amax_exp - 2, 0, 254) となり LZC は不要 (仕様書 7.4 節)。
//
//   [3/4 スケーリング unbiased 変形 — 仕様書 7.7 節 / 11 章 段階 7]
//     UNBIASED_34 = 1 にすると、shared_exp は Algorithm 1 のまま決めたうえで、
//     各要素を 3/4 倍してから量子化する。Algorithm 1 では scaled 値の最大が
//     [4, 8) に入るため 6.0 (E2M1 の最大値) を超える要素がクランプされるが、
//     3/4 倍すると最大が [3, 6) に収まりクランプが構造的に消える。
//     Tseng, Yu, Park (arXiv:2502.20586) はこの変形が入力の 3/4 の不偏推定に
//     なることを確率的丸めの条件で示している。本実装のRNEでは不偏性を保証
//     しない。デフォルトは Algorithm 1 (UNBIASED_34 = 0)。
//
//     3/4 倍は指数シフトではないので仮数の乗算になるが、3m は 24bit 仮数から
//     26bit にしか伸びないため、m1 / G / S を作るのに丸めは不要 (厳密)。
// -----------------------------------------------------------------------------
module quant_encoder
  import mxfp4_pkg::*;
#(
  parameter bit UNBIASED_34 = 1'b0    // 1: 3/4 スケーリング (仕様書 7.7 節)
) (
  input  logic               clk,
  input  logic               rst_n,
  input  logic               in_valid,
  input  logic [31:0]        v_i [K],
  output logic [BLOCK_W-1:0] blk_o,
  output logic               out_valid,
  // 観測ポート (仕様書 7.6 節。9.4 節の cg_enc 用。合成時は削除可)
  output logic signed [SCALED_EXP_W-1:0] e_rel_dbg [K],  // stage5 の要素別相対指数
  output logic [2:0]                     mag3_dbg  [K],  // stage5 の要素別量子化コード
  output logic                           tie_hit_dbg [K],// タイ点命中フラグ
  output logic                           quant_valid_dbg // stage5 の組合せが有効なサイクル
);

  // ENC_LAT は mxfp4_pkg から一元配布する (仕様書 12 章 注意 10)
  logic [ENC_LAT-1:0] valid_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) valid_q <= '0;
    else        valid_q <= {valid_q[ENC_LAT-2:0], in_valid};
  end

  assign out_valid = valid_q[ENC_LAT-1];

  // stage5 の組合せ (量子化とパック) が有効なサイクル。blk_o を載せる段レジスタの
  // 1 つ手前なので、out_valid ではなくこちらで観測すること (仕様書 9.4 節の注)。
  assign quant_valid_dbg = valid_q[ENC_LAT-2];

  // タイ点命中の判定。仕様書 7.2 節の中点 7 点にそれぞれ対応させる。
  //   e_rel = -2 : 0.25         -> m1=0, g=0, s=0
  //   e_rel = -1 : 0.75         -> m1=1, g=0, s=0  (この binade の代表点は 0.5 のみで、
  //                                中点は 0.5 と次 binade の 1.0 の間にある)
  //   e_rel =  0 : 1.25 / 1.75  -> g=1, s=0
  //   e_rel =  1 : 2.5  / 3.5   -> g=1, s=0
  //   e_rel =  2 : 5.0          -> m1=0, g=1, s=0  (m1=1 側の 7.0 は繰り上げ先 8.0 が
  //                                表現できずクランプになるためタイではない)
  //   e_rel <= -3 / >= 3        -> 常にクランプされるのでタイなし
  function automatic logic tie_of(input logic signed [SCALED_EXP_W-1:0] er,
                                  input logic [22:0]                    frac,
                                  input logic                           is_zero);
    logic m1, g, s;
    m1 = frac[22];
    g  = frac[21];
    s  = |frac[20:0];
    if (is_zero) return 1'b0;
    unique case (1'b1)
      (er == -$signed(SCALED_EXP_W'(2))): tie_of = (~m1 & ~g & ~s);
      (er == -$signed(SCALED_EXP_W'(1))): tie_of = ( m1 & ~g & ~s);
      (er ==  $signed(SCALED_EXP_W'(0))): tie_of = ( g & ~s);
      (er ==  $signed(SCALED_EXP_W'(1))): tie_of = ( g & ~s);
      (er ==  $signed(SCALED_EXP_W'(2))): tie_of = (~m1 & g & ~s);
      default:                            tie_of = 1'b0;
    endcase
  endfunction

  // ===========================================================================
  // stage1: 絶対値化 + NaN/Inf 検出 + DAZ
  // ===========================================================================
  logic [30:0] key_c [K];
  logic        spec_c;

  always_comb begin
    spec_c = 1'b0;
    for (int i = 0; i < K; i++) begin
      // DAZ: 指数フィールド 0 (ゼロ / デノーマル) は 0 として扱う (仕様書 7.5 節)
      key_c[i] = (v_i[i][30:23] == 8'h00) ? 31'd0 : v_i[i][30:0];
      // NaN / Inf はブロック単位で scale = 0xFF とし量子化をバイパスする
      if (v_i[i][30:23] == FP32_EXP_MAX) spec_c = 1'b1;
    end
  end

  logic [30:0] key_q1 [K];
  logic [31:0] v_q1 [K], v_q2 [K], v_q3 [K], v_q4 [K];
  logic        spec_q1, spec_q2, spec_q3;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (int i = 0; i < K; i++) begin
        key_q1[i] <= '0;
        v_q1[i]   <= '0;
        v_q2[i]   <= '0;
        v_q3[i]   <= '0;
        v_q4[i]   <= '0;
      end
      spec_q1 <= 1'b0;
      spec_q2 <= 1'b0;
      spec_q3 <= 1'b0;
    end else begin
      for (int i = 0; i < K; i++) begin
        key_q1[i] <= key_c[i];
        // 量子化は stage5 で行うので入力を 4 段遅延させる
        v_q1[i] <= v_i[i];
        v_q2[i] <= v_q1[i];
        v_q3[i] <= v_q2[i];
        v_q4[i] <= v_q3[i];
      end
      spec_q1 <= spec_c;
      spec_q2 <= spec_q1;
      spec_q3 <= spec_q2;
    end
  end

  // ===========================================================================
  // stage2-3: amax トーナメント
  // ===========================================================================
  logic [30:0] amax;

  amax_tree32 u_amax (
    .clk   (clk),
    .rst_n (rst_n),
    .key_i (key_q1),
    .amax_o(amax)
  );

  // ===========================================================================
  // stage4: shared_exp / X_biased
  // ===========================================================================
  logic [7:0] amax_exp;
  logic       allzero_c;
  logic [7:0] xb_c;
  e8m0_t      scale_c;
  logic       bypass_c;

  always_comb begin
    amax_exp  = amax[30:23];
    allzero_c = (amax == 31'd0);

    // X_biased = clamp(amax_exp - 2, 0, 254)
    //   amax_exp は 8bit なので amax_exp - 2 の最大は 253。したがって上限 254 の
    //   クランプは決して発火しない (amax_exp = 255 は NaN/Inf として bypass される)。
    //   実装するのは下限クランプのみ (仕様書 7.5 節: 極小 amax で相対指数が飽和)。
    xb_c = (amax_exp <= 8'd2) ? 8'd0 : (amax_exp - 8'd2);

    if (spec_q3)        scale_c = E8M0_NAN;   // ブロック単位 NaN
    else if (allzero_c) scale_c = 8'h00;      // 全ゼロブロック
    else                scale_c = xb_c;

    bypass_c = spec_q3 | allzero_c;
  end

  e8m0_t scale_q4;
  logic [7:0] xb_q4;
  logic       bypass_q4;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      scale_q4  <= 8'h00;
      xb_q4     <= 8'h00;
      bypass_q4 <= 1'b1;
    end else begin
      scale_q4  <= scale_c;
      xb_q4     <= xb_c;
      bypass_q4 <= bypass_c;
    end
  end

  // ===========================================================================
  // stage5: 32 並列量子化 + パック
  // ===========================================================================
  logic signed [SCALED_EXP_W-1:0] e_rel_raw [K];   // Algorithm 1 の相対指数
  logic signed [SCALED_EXP_W-1:0] e_rel     [K];   // 量子化器へ渡す相対指数
  logic [22:0]                    frac_eff  [K];   // 量子化器へ渡す仮数
  logic [2:0]                     mag3      [K];

  for (genvar i = 0; i < K; i++) begin : g_quant
    // V/X は指数フィールドの減算で実現できる (仕様書 7.1 節)。
    //   e_rel = exp_field(Vi/X) - 127 = exp_field(Vi) - X_biased
    assign e_rel_raw[i] = $signed({2'b00, v_q4[i][30:23]}) - $signed({2'b00, xb_q4});

    if (UNBIASED_34) begin : g_scale34
      // 有効仮数 m = {1, frac} (24bit) に対し 3m = m + 2m (26bit) を作る。
      //   値 = m x 2^(e_rel - 23) なので (3/4) 倍は 3m x 2^(e_rel - 25)。
      //   3m の MSB は m の値によって bit25 か bit24 のどちらかに来る
      //   (3m は [1.5 x 2^24, 3 x 2^24) の範囲)。正規化位置に応じて
      //   相対指数と m1 / G / S の取り出し位置を切り替える。
      //   落ちる下位ビットは sticky として frac_eff[0] へ畳み込むので、
      //   e2m1_quantize から見た m1 / G / S は厳密なままになる。
      logic [25:0] m3;
      assign m3 = {2'b00, 1'b1, v_q4[i][22:0]} + {1'b0, 1'b1, v_q4[i][22:0], 1'b0};

      assign e_rel[i]    = m3[25] ? e_rel_raw[i]
                                  : (e_rel_raw[i] - $signed(SCALED_EXP_W'(1)));
      assign frac_eff[i] = m3[25] ? {m3[24:3], |m3[2:0]}
                                  : {m3[23:2], |m3[1:0]};
    end else begin : g_alg1
      assign e_rel[i]    = e_rel_raw[i];
      assign frac_eff[i] = v_q4[i][22:0];
    end

    e2m1_quantize u_q (
      .e_rel_i  (e_rel[i]),
      .frac_i   (frac_eff[i]),
      .is_zero_i(v_q4[i][30:23] == 8'h00),
      .mag3_o   (mag3[i])
    );

    assign e_rel_dbg[i]   = e_rel[i];
    assign mag3_dbg[i]    = mag3[i];
    assign tie_hit_dbg[i] = tie_of(e_rel[i], frac_eff[i], v_q4[i][30:23] == 8'h00);
  end

  logic [ELEMS_W-1:0] elems_c;

  always_comb begin
    for (int i = 0; i < K; i++) begin
      // NaN ブロック / 全ゼロブロックは要素を 0 で埋める (仕様書 7.5 節)
      elems_c[4*i +: 4] = bypass_q4 ? 4'h0 : {v_q4[i][31], mag3[i]};
    end
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) blk_o <= '0;
    else        blk_o <= {scale_q4, elems_c};
  end

endmodule
