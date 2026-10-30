// -----------------------------------------------------------------------------
// mxfp4_lza
//   Leading Zero Anticipator。A - B (A >= B) の結果の先頭ゼロ数を、
//   減算の完了を待たずにオペランドから予測する。仕様書 5.7 節の発展課題。
//
//   狙い: near path (実効減算・指数差 0/1) では桁落ちが最大幅まで起き得るので
//   正規化に大きな左シフトが要る。LZC を減算の後ろに置くと
//     加算器 -> LZC -> シフタ
//   の直列パスになるが、LZA なら
//     加算器            ┐
//     LZA -> エンコーダ ┴-> シフタ
//   と並列にできる。これが 5.7 節の言う「LZA による正規化前倒し」である。
//
//   [予測式の導出]
//     A >= B なので、上位から見て最初に A_i != B_i となる位置 k では
//     A_k = 1, B_k = 0 である。D = A - B と置くと
//       D = 2^k + (A_low - B_low)      (low は k-1 以下)
//     となり、k より上のビットは 0 で確定する。k の 1 つ下から
//       Z_j = ~A_j & B_j       (A_j < B_j となる位置)
//     が r 個連続すると、その分だけ借りが伝播して D は 2^(k-r) の帯まで落ちる。
//     したがって D の MSB は k-r か k-r-1 のどちらかであり、
//     「最初の P (= A^B) のうち、1 つ下が Z でないもの」を選べば予測になる。
//       f_i = P_i & ~Z_{i-1}       (Z_{-1} = 0)
//     r = 0 の場合も含めて誤差は必ず 0 か 1 に収まるので、呼び出し側の
//     1bit 補正シフトで正規化が完了する。A != B なら f はどこかで必ず 1 に
//     なる (最下位まで Z が続く場合は Z_{-1} = 0 より f_0 = P_0 = 1)。
//
//     A >= B は near path の前提から保証される:
//       指数差 0 -> a_ge が仮数比較で決まるので sig_l >= sig_s
//       指数差 1 -> sig_l_ext >= 2^26 > 2^26 - 1 >= (ext_s >> 1)
//
//   出力は「bit(ALIGN_W-2) を基準にした先頭ゼロ数」。統合パスの LZC が返す
//   nlz と同じ意味なので、そのまま左シフト量として使える。
//   予測誤差が 0 か 1 に収まっていることは tb_nearfar が毎回検査する。
// -----------------------------------------------------------------------------
module mxfp4_lza
  import mxfp4_pkg::*;
(
  input  logic [ALIGN_W-1:0] a_i,        // 被減数 (a_i >= b_i であること)
  input  logic [ALIGN_W-1:0] b_i,        // 減数
  output logic [4:0]         nlz_pred_o  // 予測される先頭ゼロ数
);

  logic [ALIGN_W-1:0] p_bits, z_bits, f_bits;

  always_comb begin
    for (int i = 0; i < ALIGN_W; i++) begin
      p_bits[i] = a_i[i] ^ b_i[i];
      z_bits[i] = ~a_i[i] & b_i[i];
    end
  end

  always_comb begin
    for (int i = 0; i < ALIGN_W; i++) begin
      logic zprev;
      zprev     = (i == 0) ? 1'b0 : z_bits[i-1];
      f_bits[i] = p_bits[i] & ~zprev;
    end
  end

  // f の先頭 1 の位置を先頭ゼロ数へ変換する (統合パスの LZC と同じ基準)
  always_comb begin
    nlz_pred_o = 5'(ALIGN_W-2);          // f が全ゼロ = A == B (完全相殺)
    for (int i = ALIGN_W-2; i >= 0; i--) begin
      if (f_bits[i]) begin
        nlz_pred_o = 5'(ALIGN_W-2 - i);
        break;
      end
    end
  end

endmodule
