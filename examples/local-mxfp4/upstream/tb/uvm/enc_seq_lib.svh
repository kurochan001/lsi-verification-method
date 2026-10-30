// -----------------------------------------------------------------------------
// enc_seq_lib (付録A A.4.3〜A.4.5 を quant_encoder レベルへ適用したもの)
//   仕様書 9.3 節のシナリオ D5 / R3 に対応する。
//
//   **D5 のうち e2m1_quantize 単体の全数照合はここでは扱わない。**
//   D5 は「単体インスタンスに e_rel を直接駆動し、統合エンコーダでは到達しない
//   default 分岐 (e_rel >= 3) も検査する」と規定されており (仕様書 9.3 節)、
//   DUT が quant_encoder ではなく e2m1_quantize になる。プレーン SV 版
//   tb_quant_encoder の test_d5_unit() が既定側としてそれを担っている
//   (cg_enc が e_rel >= 3 を ignore_bins にしているのも同じ理由)。
//   ここで扱うのは、エンコーダ経由で到達できる D5b (タイ 7 点 ±1ulp と
//   クランプ) と 7.5 節のエッジケース、および R3 のランダム往復である。
//
//   パックはしないので (enc_item は FP32 の配列をそのまま持つ)、
//   #1167 / #1170 系の制約は掛からない。ただしクラスプロパティの
//   unpacked 配列へは要素ごとではなくローカルに組み立てて全体代入する運用は
//   維持する (README の落とし穴 4b)。
// -----------------------------------------------------------------------------

// 共通ユーティリティ (A.4.3 の base_seq に相当)
virtual class enc_base_seq extends uvm_sequence #(enc_item);

  function new(string name = "enc_base_seq");
    super.new(name);
  endfunction

  // FP32 の組み立て
  static function bit [31:0] fp32(input bit s, input int exp_f, input bit [22:0] frac);
    return {s, exp_f[7:0], frac};
  endfunction

  // 1 ブロック投入する。v はローカルで組み立ててから全体代入する。
  task automatic send_block(input bit [31:0] v [K]);
    enc_item tr;
    tr = enc_item::type_id::create("tr");
    start_item(tr);
    tr.v = v;
    finish_item(tr);
  endtask
endclass

// -----------------------------------------------------------------------------
// d5b_tie_seq : タイ 7 点 ±1ulp をエンコーダ経由で確認する (仕様書 9.3 節 D5)
//   要素 0 に amax = 6.0 を置くと X_biased = 127 (X = 1.0) となり、
//   scaled 値が入力値そのものになる。残りの要素にタイ点と ±1ulp を並べる。
// -----------------------------------------------------------------------------
class d5b_tie_seq extends enc_base_seq;
  `uvm_object_utils(d5b_tie_seq)

  function new(string name = "d5b_tie_seq");
    super.new(name);
  endfunction

  task body();
    bit [31:0] v [K];
    bit [31:0] tie [7];

    tie[0] = 32'h3E800000;  // 0.25
    tie[1] = 32'h3F400000;  // 0.75
    tie[2] = 32'h3FA00000;  // 1.25
    tie[3] = 32'h3FE00000;  // 1.75
    tie[4] = 32'h40200000;  // 2.5
    tie[5] = 32'h40600000;  // 3.5
    tie[6] = 32'h40A00000;  // 5.0

    for (int d = -1; d <= 1; d++) begin
      for (int i = 0; i < K; i++) v[i] = 32'h00000000;
      v[0] = 32'h40C00000;                                    // 6.0 (amax)
      for (int t = 0; t < 7; t++) begin
        v[1 + t]     = 32'(int'(tie[t]) + d);                 // +x
        v[1 + 7 + t] = 32'(int'(tie[t]) + d) | 32'h8000_0000; // -x
      end
      send_block(v);
    end

    // 6.0 超 (クランプ) と E == 2 の繰り上げ禁止 (仕様書 7.2 節)
    for (int i = 0; i < K; i++) v[i] = 32'h00000000;
    v[0] = 32'h41000000;   // 8.0 (amax) -> X = 2.0、scaled 4.0
    v[1] = 32'h40E00000;   // 7.0 -> scaled 3.5 -> タイ -> 4.0 (110)
    v[2] = 32'h40F00000;   // 7.5 -> scaled 3.75 -> 4.0 (110)
    v[3] = 32'h40C00000;   // 6.0 -> scaled 3.0 -> 3.0 (101)
    send_block(v);
  endtask
endclass

// -----------------------------------------------------------------------------
// enc_edge_seq : 仕様書 7.5 節のエッジケース
//   全ゼロ / -0.0 のみ / NaN 混入 / Inf 混入 / デノーマルのみ (DAZ) /
//   amax 極小 (X_biased 下限 0 クランプ)
// -----------------------------------------------------------------------------
class enc_edge_seq extends enc_base_seq;
  `uvm_object_utils(enc_edge_seq)

  function new(string name = "enc_edge_seq");
    super.new(name);
  endfunction

  task body();
    bit [31:0] v [K];

    // 全ゼロブロック -> scale 0x00、要素すべて 0
    for (int i = 0; i < K; i++) v[i] = 32'h00000000;
    send_block(v);

    // -0.0 だけのブロックでも要素は 0000
    for (int i = 0; i < K; i++) v[i] = 32'h80000000;
    send_block(v);

    // NaN を 1 つ含む -> ブロック単位 scale = 0xFF
    for (int i = 0; i < K; i++) v[i] = 32'h3F800000;
    v[5] = 32'h7FC00000;
    send_block(v);

    // Inf を 1 つ含む -> 同上
    for (int i = 0; i < K; i++) v[i] = 32'h3F800000;
    v[31] = 32'h7F800000;
    send_block(v);

    // デノーマルのみ -> DAZ により全ゼロ扱い
    for (int i = 0; i < K; i++) v[i] = 32'h00000001;
    send_block(v);

    // amax が極小 (X_biased 下限 0 クランプ。仕様書 7.5 節 / 12 章 注意 3)
    for (int i = 0; i < K; i++) v[i] = 32'h00000000;
    v[0] = fp32(1'b0, 1, 23'h000000);   // 2^-126
    v[1] = fp32(1'b0, 1, 23'h400000);   // 1.5 * 2^-126
    send_block(v);
  endtask
endclass

// -----------------------------------------------------------------------------
// r3_rand_seq : ランダム往復 (仕様書 9.3 節 R3)
//   ブロックごとにダイナミックレンジを変える。enc_item の c_win 制約が
//   emin / emax の窓を与えるので、その中で要素を散らす。
// -----------------------------------------------------------------------------
class r3_rand_seq extends enc_base_seq;
  `uvm_object_utils(r3_rand_seq)

  int unsigned n_blocks = 30;

  function new(string name = "r3_rand_seq");
    super.new(name);
  endfunction

  task body();
    enc_item tr;
    bit [31:0] v [K];
    int e;

    for (int b = 0; b < n_blocks; b++) begin
      tr = enc_item::type_id::create("tr");
      start_item(tr);
      if (!tr.randomize())
        `uvm_fatal("R3", "enc_item randomize failed")
      // 指数窓の中へ収め直す。制約ソルバに 32 要素 x FP32 を解かせる必然性は
      // ないので、窓 (emin/emax) だけを randomize で決めて値はここで作る
      // (付録A レビュー 3 節の方針と同じ)。
      for (int i = 0; i < K; i++) begin
        e    = tr.emin + ($urandom_range(0, tr.emax - tr.emin));
        v[i] = fp32(bit'($urandom_range(0, 1)), e, 23'($urandom));
      end
      tr.v = v;
      finish_item(tr);
    end
  endtask
endclass
