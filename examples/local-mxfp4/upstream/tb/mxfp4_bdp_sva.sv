// -----------------------------------------------------------------------------
// mxfp4_bdp_sva
//   ブロック内積ユニットのアサーション。仕様書 9.5 節。
//   末尾の bind 文により mxfp4_bdp の全インスタンスへ自動的に接続される
//   (GEMM の 16 PE を含む)。このファイルをコンパイル対象に加えるだけでよい。
//
//   実行にはアサーション有効化オプションが要る
//   (Verilator は --assert、sukimasim は -assert)。
// -----------------------------------------------------------------------------
module mxfp4_bdp_sva
  import mxfp4_pkg::*;
(
  input logic               clk,
  input logic               rst_n,
  input logic               in_valid,
  input logic               in_ready,
  input logic               first,
  input logic               last,
  input logic [BLOCK_W-1:0] a_block,
  input logic [BLOCK_W-1:0] b_block,
  input logic               out_valid,
  input logic               out_ready,
  input logic [31:0]        result,
  input logic               gradual_uf_dbg   // 1 なら 6.3 節の発展課題モード
);

  // ---------------------------------------------------------------------------
  // タイミング系プロパティのサンプリング (仕様書 3.3 節の ready 拡張)
  //   mxfp4_bdp は out_valid && !out_ready の間パイプライン全体をストールさせ、
  //   その間 in_ready を 0 にする。したがって「投入から LAT 段」を数えるには
  //   in_ready = 1 のサイクルだけをティックとみなす必要がある。
  //   クロッキングイベントの iff 修飾は IEEE 1800-2023 §9.4.2.3 の条件付き
  //   イベント制御であり、§16.14.6 の例 (@(posedge clock iff reset == 0)) の
  //   とおりアサーションのクロックとしても使える。
  //   out_ready を常時 1 に固定した構成では in_ready も常時 1 になるので、
  //   ready 拡張前とまったく同じサンプリングに退化する。
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // out_valid は last から LAT 転送サイクル後にのみ立つ
  // ---------------------------------------------------------------------------
  property p_latency;
    @(posedge clk iff in_ready) disable iff (!rst_n)
      (in_valid && last) |-> ##LAT out_valid;
  endproperty
  a_latency: assert property (p_latency)
    else $error("p_latency: out_valid did not rise LAT=%0d transfers after last", LAT);

  // 逆向き: out_valid が立つときは LAT サイクル前に last が入っていたこと。
  //
  // $past の第 1 引数には中間信号を渡すこと。式 ($past(in_valid && last, LAT))
  // を直接渡すと sukimasim 0.9.9.2 は 1 tick 余分に遅れた値を返す
  // (IEEE 1800-2023 §16.9.3 は expression1 に任意の式を許し、k 番目の
  // strictly prior なティックのサンプル値を返すと規定しているので LRM 違反)。
  // 単一信号を渡す形なら両シミュレータとも規定どおりに動く。
  logic accept_last;
  assign accept_last = in_valid && in_ready && last;

  property p_ovalid_cause;
    @(posedge clk iff in_ready) disable iff (!rst_n)
      out_valid |-> $past(accept_last, LAT);
  endproperty
  a_ovalid_cause: assert property (p_ovalid_cause)
    else $error("p_ovalid_cause: out_valid without a matching last");

  // ---------------------------------------------------------------------------
  // NaN スケール入力なら結果は qNaN (仕様書 2.4 節 / 6 章)
  // ---------------------------------------------------------------------------
  property p_nan;
    @(posedge clk iff in_ready) disable iff (!rst_n)
      (in_valid && last && (a_block[BLOCK_W-1 -: 8] == E8M0_NAN ||
                            b_block[BLOCK_W-1 -: 8] == E8M0_NAN))
      |-> ##LAT (out_valid && result == FP32_QNAN);
  endproperty
  a_nan: assert property (p_nan)
    else $error("p_nan: NaN scale did not produce qNaN");

  // ---------------------------------------------------------------------------
  // ハンドシェイク規約 (仕様書 3.3 節。AMBA AXI §A3.2.1 と同じ規約)
  //   ソース側の義務: valid を立てたら転送が起きるまで valid とデータを保持する。
  //   out_ready を常時 1 に固定した構成では in_ready も常時 1 なので vacuous。
  // ---------------------------------------------------------------------------
  property p_hold;
    @(posedge clk) disable iff (!rst_n)
      (in_valid && !in_ready) |=> in_valid;
  endproperty
  a_hold: assert property (p_hold)
    else $error("p_hold: valid dropped before being accepted");

  property p_hold_data;
    @(posedge clk) disable iff (!rst_n)
      (in_valid && !in_ready) |=> ($stable(a_block) && $stable(b_block) &&
                                   $stable(first)   && $stable(last));
  endproperty
  a_hold_data: assert property (p_hold_data)
    else $error("p_hold_data: input data changed before being accepted");

  // ---------------------------------------------------------------------------
  // デスティネーション側の義務: out_valid は out_ready が立つまで下ろさず、
  // その間 result を保持する (仕様書 3.3 節の ready 拡張)。
  // ---------------------------------------------------------------------------
  property p_stall_hold;
    @(posedge clk) disable iff (!rst_n)
      (out_valid && !out_ready) |=> (out_valid && $stable(result));
  endproperty
  a_stall_hold: assert property (p_stall_hold)
    else $error("p_stall_hold: out_valid/result not held while stalled");

  // ストール中は新しい投入を受け付けない (パイプラインが進まないこと)
  property p_stall_blocks_input;
    @(posedge clk) disable iff (!rst_n)
      (out_valid && !out_ready) |-> !in_ready;
  endproperty
  a_stall_blocks_input: assert property (p_stall_blocks_input)
    else $error("p_stall_blocks_input: in_ready asserted while stalled");

  // ---------------------------------------------------------------------------
  // FTZ: 出力は正規 / ゼロ / Inf / NaN のみ (デノーマル禁止。仕様書 6.3 節)
  //   gradual underflow モード (発展課題) ではデノーマル出力が正当なので外す。
  // ---------------------------------------------------------------------------
  property p_no_denorm;
    @(posedge clk) disable iff (!rst_n)
      (out_valid && !gradual_uf_dbg)
      |-> !((result[30:23] == 8'h00) && (result[22:0] != 23'h0));
  endproperty
  a_no_denorm: assert property (p_no_denorm)
    else $error("p_no_denorm: denormal output %h", result);

  // ---------------------------------------------------------------------------
  // 完全相殺・アンダーフローの結果は +0 (符号付きゼロは -0 も許すが、
  // RNE の規定により完全相殺は +0。FTZ は符号保持なので -0 もあり得る)
  // ここでは「ゼロなら仮数も 0」であることだけを確認する。
  // ---------------------------------------------------------------------------
  property p_zero_clean;
    @(posedge clk) disable iff (!rst_n)
      (out_valid && !gradual_uf_dbg && (result[30:23] == 8'h00))
      |-> (result[22:0] == 23'h0);
  endproperty
  a_zero_clean: assert property (p_zero_clean)
    else $error("p_zero_clean: zero result with nonzero fraction %h", result);

endmodule

// mxfp4_bdp の全インスタンスへ接続する (単体 TB / GEMM の 16 PE を問わない)
bind mxfp4_bdp mxfp4_bdp_sva u_sva (.*);
