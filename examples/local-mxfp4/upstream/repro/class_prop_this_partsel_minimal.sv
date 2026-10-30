// -----------------------------------------------------------------------------
// this. で修飾したクラスプロパティへの部分代入が丸ごと落ちる — 最小再現
//
//   対象: sukimasim 0.9.9.2 (2026-08-13 18:01 ビルド)
//   Issue: #1206 (2026-08-13 発行)
//   前身: Issue #1170 (CLOSED)。同 issue の修正 67149cced 後は 15 ケース中 14 が
//         PASS で、`this.` を明示した 1 ケースだけが残っていた。
//         スピンオフ先の #1175 は stale-mirror ヒューリスティックの件で、
//         こちらの lvalue 経路とは別。残件が独立 issue になっていなかったので発行した。
//   規格: IEEE 1800-2023 §8.11 (This)、§11.5.1 (Vector bit-select and part-select
//         addressing)、§10.4 (Procedural assignments)
//
//   LRM の規定:
//     §8.11 "The this keyword is used to unambiguously refer to class properties
//            ... of the current instance."
//     §8.11 NOTE "In writing methods, members can be qualified with this to refer
//            to the current instance, but it is usually unnecessary."
//     つまり非静的メソッド内の `this.p` と裸の `p` は**同一オブジェクトの同一
//     プロパティ**を指す。修飾の有無で代入の意味論は変わらない。
//     §11.5.1 により部分代入は「指定ビットだけを更新し、他は保持する」。
//
//   観測される症状 (sukimasim 0.9.9.2):
//     クラスメソッド内でプロパティへ部分代入するとき、左辺を `this.` で修飾すると
//     書き込みが**1 回目から丸ごと落ちる** (プロパティは 0 のまま)。
//     裸名で同じ書き込みをすると正しく効く。#1170 の元症状 (2 回目以降が落ちる)
//     とは壊れ方が違う。
//
//   このファイルの構成:
//     すべてのケースを `this.` あり / なしの**双子**にして同じ実行の中に並べてある。
//     期待値はクラスの外で決めているので、壊れうる経路の外にある。
//
//   実行 (行頭に "verilator" を置くと BADVLTPRAGMA になるため $ で始める):
//     $ sukimasim -top tb_class_prop_this class_prop_this_partsel_minimal.sv
//     $ verilator --binary --timing --timescale 1ns/1ps \
//         --top-module tb_class_prop_this class_prop_this_partsel_minimal.sv
//
//   期待値 (Verilator 5.048 はこうなる): n_fail = 0
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_class_prop_this;

  int n_check = 0;
  int n_fail  = 0;

  function automatic void chk(input string nm,
                              input logic [135:0] got,
                              input logic [135:0] exp);
    n_check++;
    if (got !== exp) begin
      n_fail++;
      $display("[FAIL] %-40s got=%034h exp=%034h", nm, got, exp);
    end else begin
      $display("[ ok ] %-40s     %034h", nm, got);
    end
  endfunction

  // ---------------------------------------------------------------------------
  // 被験クラス。同じ書き込みを this. あり / なしの対で持つ
  // ---------------------------------------------------------------------------
  class C;
    bit [135:0] w136;
    bit [31:0]  w32;
    bit [7:0]   w8;
    bit [3:0]   el [8];

    function void fill_elems();
      foreach (el[i]) el[i] = 4'(i + 1);        // 1,2,...,8
    endfunction

    // 1) 可変 part-select (foreach)
    function void var_this();  foreach (el[i]) this.w136[4*i +: 4] = el[i]; endfunction
    function void var_bare();  foreach (el[i]) w136[4*i +: 4] = el[i];      endfunction

    // 2) 定数 part-select を 1 回だけ (「最初の 1 回も落ちるか」の決定打)
    function void one_this();  this.w136[3:0] = 4'h1; endfunction
    function void one_bare();  w136[3:0] = 4'h1;      endfunction

    // 3) 定数 part-select を 3 回
    function void three_this();
      this.w136[3:0]  = 4'h1;
      this.w136[7:4]  = 4'h2;
      this.w136[11:8] = 4'h3;
    endfunction
    function void three_bare();
      w136[3:0]  = 4'h1;
      w136[7:4]  = 4'h2;
      w136[11:8] = 4'h3;
    endfunction

    // 4) bit-select を 1 回だけ
    function void bit1_this(); this.w136[0] = 1'b1; endfunction
    function void bit1_bare(); w136[0] = 1'b1;      endfunction

    // 5) bit-select を 8 回
    function void bit8_this(); for (int i = 0; i < 8; i++) this.w136[i] = 1'b1; endfunction
    function void bit8_bare(); for (int i = 0; i < 8; i++) w136[i] = 1'b1;      endfunction

    // 6) 幅の依存を見る (136 / 32 / 8bit)
    function void w32_this(); foreach (el[i]) this.w32[4*i +: 4] = el[i]; endfunction
    function void w32_bare(); foreach (el[i]) w32[4*i +: 4] = el[i];      endfunction
    function void w8_this();  for (int i = 0; i < 2; i++) this.w8[4*i +: 4] = el[i]; endfunction
    function void w8_bare();  for (int i = 0; i < 2; i++) w8[4*i +: 4] = el[i];      endfunction

    // 7) 全体代入なら this. でも通るか (回避策が this. 付きでも成立するか)
    function void whole_this(); this.w136 = 136'h87654321; endfunction

    // 8) 読み side の this. は無事か
    function bit [135:0] read_this(); return this.w136; endfunction

    // 9) 同じメソッドの中で this. あり / なしを混ぜる
    function void mix_this_first();
      this.w136[3:0] = 4'h1;
      w136[7:4]      = 4'h2;
    endfunction
    function void mix_bare_first();
      w136[3:0]      = 4'h1;
      this.w136[7:4] = 4'h2;
    endfunction

    // 10) task 本体でも同じか
    task var_this_task(); foreach (el[i]) this.w136[4*i +: 4] = el[i]; endtask
    task var_bare_task(); foreach (el[i]) w136[4*i +: 4] = el[i];      endtask
  endclass

  // 11) コンストラクタ内の this. 部分代入
  class Ctor;
    bit [135:0] w;
    function new(input bit use_this);
      if (use_this) for (int i = 0; i < 8; i++) this.w[4*i +: 4] = 4'(i + 1);
      else          for (int i = 0; i < 8; i++)      w[4*i +: 4] = 4'(i + 1);
    endfunction
  endclass

  C    c;
  Ctor k_this, k_bare;
  bit [135:0] rd;

  initial begin
    c = new();
    c.fill_elems();

    $display("--- PART A: 同じ書き込みを this. あり / なしで対にする ---");

    c.w136 = '0; c.var_bare();
    chk("1a) foreach part-select / bare",    c.w136, 136'h87654321);
    c.w136 = '0; c.var_this();
    chk("1b) foreach part-select / this.",   c.w136, 136'h87654321);

    c.w136 = '0; c.one_bare();
    chk("2a) single const part-select / bare",  c.w136, 136'h1);
    c.w136 = '0; c.one_this();
    chk("2b) single const part-select / this.", c.w136, 136'h1);

    c.w136 = '0; c.three_bare();
    chk("3a) const part-select x3 / bare",   c.w136, 136'h321);
    c.w136 = '0; c.three_this();
    chk("3b) const part-select x3 / this.",  c.w136, 136'h321);

    c.w136 = '0; c.bit1_bare();
    chk("4a) single bit-select / bare",      c.w136, 136'h1);
    c.w136 = '0; c.bit1_this();
    chk("4b) single bit-select / this.",     c.w136, 136'h1);

    c.w136 = '0; c.bit8_bare();
    chk("5a) bit-select x8 / bare",          c.w136, 136'hff);
    c.w136 = '0; c.bit8_this();
    chk("5b) bit-select x8 / this.",         c.w136, 136'hff);

    $display("--- PART B: 幅に依存するか ---");

    c.w32 = '0; c.w32_bare();
    chk("6a) 32bit property / bare",         {104'h0, c.w32}, 136'h87654321);
    c.w32 = '0; c.w32_this();
    chk("6b) 32bit property / this.",        {104'h0, c.w32}, 136'h87654321);

    c.w8 = '0; c.w8_bare();
    chk("7a) 8bit property / bare",          {128'h0, c.w8},  136'h21);
    c.w8 = '0; c.w8_this();
    chk("7b) 8bit property / this.",         {128'h0, c.w8},  136'h21);

    $display("--- PART C: 全体代入と読み ---");

    c.w136 = '0; c.whole_this();
    chk("8) whole assignment / this.",       c.w136, 136'h87654321);

    c.w136 = '0;
    c.w136 = 136'hdeadbeef;
    rd = c.read_this();
    chk("9) read through this.",             rd, 136'hdeadbeef);

    $display("--- PART D: this. あり / なしを混ぜる ---");

    c.w136 = '0; c.mix_bare_first();
    chk("10a) bare then this.",              c.w136, 136'h21);
    c.w136 = '0; c.mix_this_first();
    chk("10b) this. then bare",              c.w136, 136'h21);

    $display("--- PART E: task とコンストラクタ ---");

    c.w136 = '0; c.var_bare_task();
    chk("11a) task body / bare",             c.w136, 136'h87654321);
    c.w136 = '0; c.var_this_task();
    chk("11b) task body / this.",            c.w136, 136'h87654321);

    k_bare = new(1'b0);
    chk("12a) constructor / bare",           k_bare.w, 136'h87654321);
    k_this = new(1'b1);
    chk("12b) constructor / this.",          k_this.w, 136'h87654321);

    $display("=====================================");
    $display(" class_prop_this_partsel_minimal : %0d checks, %0d failures", n_check, n_fail);
    if (n_fail == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
