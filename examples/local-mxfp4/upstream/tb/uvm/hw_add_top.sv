// -----------------------------------------------------------------------------
// hw_add_top
//   FP32 加算器単体レベルの UVM トップ (付録A A.10 / 図11 の add_core env)。
//   DUT は mxfp4_fp32_add_core 1 つだけ。
//
//   GRADUAL_UF は既定の 0 (仕様書 6.3 節の発展課題は既定オフ)。
//   段階 7 の gradual 版を検証するなら別トップを立てること。
//
//   DUT は組合せ回路なのでクロックを持たない。clk は TB 側の駆動 / 観測の
//   タイミングを揃えるためだけに使う (driver が negedge で駆動し、
//   monitor が posedge で採る)。rst_n も同じく開始点を揃えるためだけで、
//   DUT へは繋がない。
//
//   addcore_if のメンバはすべて packed / スカラなので、Issue #1320
//   (interface の unpacked 配列がポート接続されると書き込みが届かない) は
//   踏まない。unpacked 配列を足す必要が出たら module スコープで展開すること。
//
//   駆動信号に宣言時初期値は付けない (README の落とし穴 1)。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module hw_add_top;
  import uvm_pkg::*;
  import mxfp4_pkg::*;
  import mxfp4_uvm_pkg::*;

  logic clk;
  hw_clkgen u_clkgen (.clk(clk));

  addcore_if add_i(clk);

  // ---------------------------------------------------------------------------
  // DUT: mxfp4_fp32_add_core (組合せ)
  // ---------------------------------------------------------------------------
  mxfp4_fp32_add_core #(
    .GRADUAL_UF (1'b0)
  ) u_add (
    .a_sign      (add_i.a_sign),
    .a_exp       (add_i.a_exp),
    .a_sig       (add_i.a_sig),
    .b_sign      (add_i.b_sign),
    .b_exp       (add_i.b_exp),
    .b_sig       (add_i.b_sig),
    .r_sign      (add_i.r_sign),
    .r_exp       (add_i.r_exp),
    .r_sig       (add_i.r_sig),
    .r_carry_ovf (add_i.r_carry_ovf),
    .r_zero      (add_i.r_zero)
  );

  // ---------------------------------------------------------------------------
  // 駆動信号の初期化 (DUT にリセットは無い。driver / monitor の開始点合わせ)
  // ---------------------------------------------------------------------------
  initial begin
    add_i.rst_n    = 1'b1;
    add_i.in_valid = 1'b0;
    add_i.a_sign   = 1'b0;
    add_i.a_exp    = '0;
    add_i.a_sig    = '0;
    add_i.b_sign   = 1'b0;
    add_i.b_exp    = '0;
    add_i.b_sig    = '0;
    #1 add_i.rst_n = 1'b0;
    repeat (5) @(negedge clk);
    add_i.rst_n = 1'b1;
  end

  // ---------------------------------------------------------------------------
  // virtual interface の受け渡しと起動 (A.3.3)
  // ---------------------------------------------------------------------------
  initial begin
    uvm_config_db#(virtual addcore_if)::set(null, "*", "addcore_vif", add_i);
    run_test();
  end

endmodule
