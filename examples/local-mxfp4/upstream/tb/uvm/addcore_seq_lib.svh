// -----------------------------------------------------------------------------
// addcore_seq_lib (付録A A.10、シナリオ R2f)
//   加算器単体へ任意の FP32 を直接与える。
//
//   R2f を独立に置く理由 (仕様書 9.3 節の注): BDP 経由のテスト (R2a 等) では
//   第 2 項が i2f 由来で有効仮数が 13bit しかなく、アライン量 14 以下では
//   sticky が立たない。桁上げ + sticky の丸め経路は、任意の 24bit 仮数を
//   直接与えられる単体テストでしか踏めない。
//
//   分布は addcore_item の c_mode 制約が持っている
//   (0: 同符号 + 指数差 1..30 が 70%、1: 完全相殺 10%、2: 一様 20%)。
//   ここではそれを回すだけにして、制約をシーケンス側へ二重に書かない。
// -----------------------------------------------------------------------------

// 共通ユーティリティ
virtual class addcore_base_seq extends uvm_sequence #(addcore_item);

  function new(string name = "addcore_base_seq");
    super.new(name);
  endfunction

  // FP32 のビットパターンから 1 件投入する (directed 用)
  task automatic send_fp32(input bit [31:0] x, input bit [31:0] y);
    addcore_item tr;
    tr = addcore_item::type_id::create("tr");
    start_item(tr);
    tr.a_sign = x[31];
    tr.a_exp  = signed'({3'b000, x[30:23]});
    tr.a_sig  = {1'b1, x[22:0]};
    tr.b_sign = y[31];
    tr.b_exp  = signed'({3'b000, y[30:23]});
    tr.b_sig  = {1'b1, y[22:0]};
    finish_item(tr);
  endtask
endclass

// -----------------------------------------------------------------------------
// r2f_directed_seq : 既知の境界ケース
//   A1 は Rev.1.0 のフィードバックで仕様書チームから指摘された反例
//   (桁上げ時に sticky を落とすと外れる。docs/spec_feedback_rev1.0.md A1)。
// -----------------------------------------------------------------------------
class r2f_directed_seq extends addcore_base_seq;
  `uvm_object_utils(r2f_directed_seq)

  function new(string name = "r2f_directed_seq");
    super.new(name);
  endfunction

  task body();
    // A1 反例: 桁上げ + sticky
    send_fp32(32'h417C7180, 32'h3F00FC52);
    // 完全相殺 (同指数・同仮数・逆符号) -> r_zero = 1 かつ +0
    send_fp32(32'h40490FDB, 32'hC0490FDB);
    send_fp32(32'h3F800000, 32'hBF800000);
    // 同符号・同値 (仮数の桁上げでちょうど 1 段上がる)
    send_fp32(32'h3F800000, 32'h3F800000);
    // 指数差が大きく、加算前後で値が変わらない (b が完全に落ちる)
    send_fp32(32'h7F000000, 32'h00800000);
    // タイ (RNE の偶数丸め): 1.0 + 2^-24 は 1.0 のまま
    send_fp32(32'h3F800000, 32'h33800000);
    // タイの一つ上: 1.0 + 3*2^-25 は 1 ulp 上がる
    send_fp32(32'h3F800000, 32'h34400000);
  endtask
endclass

// -----------------------------------------------------------------------------
// r2f_rand_seq : 制約付きランダム (R2f の本体)
// -----------------------------------------------------------------------------
class r2f_rand_seq extends addcore_base_seq;
  `uvm_object_utils(r2f_rand_seq)

  int unsigned n_pairs = 200;
  // mode の実現数 (制約は dist { 0 := 70, 1 := 10, 2 := 20 })
  int unsigned n_mode [3];
  int unsigned n_sc_fail;

  function new(string name = "r2f_rand_seq");
    super.new(name);
  endfunction

  task body();
    addcore_item tr;
    n_mode = '{0, 0, 0};
    n_sc_fail = 0;
    for (int i = 0; i < n_pairs; i++) begin
      tr = addcore_item::type_id::create("tr");
      start_item(tr);
      if (!tr.randomize())
        `uvm_fatal("R2F", "addcore_item randomize failed")
      if (tr.mode < 3) n_mode[tr.mode]++;
      if (!tr.sc_ok)   n_sc_fail++;
      finish_item(tr);
    end
    `uvm_info("R2F", $sformatf("mode counts: 0(band)=%0d 1(cancel)=%0d 2(uniform)=%0d  constraint self-check failures=%0d",
              n_mode[0], n_mode[1], n_mode[2], n_sc_fail), UVM_LOW)
  endtask
endclass
