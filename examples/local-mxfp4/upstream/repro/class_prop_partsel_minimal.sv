// -----------------------------------------------------------------------------
// クラスメソッド内からクラスプロパティへ部分代入すると 2 回目以降が無視される
// — 最小再現
//
//   対象: sukimasim 0.9.9.2 (Issue #1170)
//   規格: IEEE 1800-2023 §11.5.1 (Vector bit-select and part-select addressing)
//         §10.4 (Procedural assignments)、§8.3 (Class properties)
//
//   LRM の規定:
//     クラスプロパティは通常の変数と同じ左辺値であり、bit-select / part-select
//     への手続き代入は「指定ビットだけを更新し、他のビットは保持する」。
//     クラスメソッド内から書くか外から書くかで意味論は変わらない。
//
//   観測される症状 (sukimasim 0.9.9.2):
//     クラスメソッド (function / task) の中でプロパティに部分代入すると、
//     「直前の全体代入以降、最初の 1 回」だけが反映され、2 回目以降は
//     黙って捨てられる。全体代入 (prop = value) を挟むと、その直後の
//     部分代入は再び 1 回だけ効く。
//     さらにメソッドを抜けた後に外から読むと、メソッド内で見えていた値とも
//     食い違うことがある (PART C)。
//
//     幅 (8 / 32 / 136bit)、定数 part-select か可変 part-select か、
//     bit-select か、function か task か、`this.` を明示するかは無関係。
//     壊れるのは「クラスメソッド内から」書いたときだけで、
//       - モジュール変数への部分代入
//       - 関数ローカル変数への部分代入
//       - クラス外 (module の initial 等) からプロパティへの部分代入
//     はいずれも正しく動く (PART A の 4)〜6))。
//
//   実務上の影響:
//     ビットフィールドをクラス内で組み立てるコードが黙って壊れる。
//     UVM のトランザクションクラスでパック関数を書くと踏む
//     (本プロジェクトでは付録A の blk_pair_item::pack_blocks() で踏んだ)。
//
//   回避策:
//     メソッド内ではローカル変数に組み立て、最後にプロパティへ全体代入する。
//
//   実行 (行頭に "verilator" を置くと BADVLTPRAGMA になるため $ で始める):
//     $ sukimasim -top tb_class_prop_partsel class_prop_partsel_minimal.sv
//     $ verilator --binary --timing --timescale 1ns/1ps \
//         --top-module tb_class_prop_partsel class_prop_partsel_minimal.sv
//
//   期待値 (Verilator 5.048 はこうなる): n_fail = 0
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_class_prop_partsel;

  int n_check = 0;
  int n_fail  = 0;

  function automatic void chk(input string nm,
                              input logic [135:0] got,
                              input logic [135:0] exp);
    n_check++;
    if (got !== exp) begin
      n_fail++;
      $display("[FAIL] %-38s got=%034h exp=%034h", nm, got, exp);
    end else begin
      $display("[ ok ] %-38s     %034h", nm, got);
    end
  endfunction

  // ---------------------------------------------------------------------------
  // 被験クラス
  // ---------------------------------------------------------------------------
  class C;
    bit [135:0] w136;
    bit [31:0]  w32;
    bit [7:0]   w8;
    bit [3:0]   el [8];

    function void fill_elems();
      foreach (el[i]) el[i] = 4'(i + 1);      // 1,2,...,8
    endfunction

    // 1) メソッド内 / foreach + 可変 part-select
    function void pack_foreach();
      foreach (el[i]) w136[4*i +: 4] = el[i];
    endfunction

    // 2) メソッド内 / 定数 part-select を 3 回
    function void pack_const();
      w136[3:0]  = 4'h1;
      w136[7:4]  = 4'h2;
      w136[11:8] = 4'h3;
    endfunction

    // 3) メソッド内 / bit-select を 8 回
    function void pack_bits();
      for (int i = 0; i < 8; i++) w136[i] = 1'b1;
    endfunction

    // 4) メソッド内 / task 版
    task pack_task();
      foreach (el[i]) w136[4*i +: 4] = el[i];
    endtask

    // 5) メソッド内 / this. を明示
    function void pack_this();
      foreach (el[i]) this.w136[4*i +: 4] = el[i];
    endfunction

    // 6) 幅の小さいプロパティ
    function void pack32();
      foreach (el[i]) w32[4*i +: 4] = el[i];
    endfunction

    function void pack8();
      for (int i = 0; i < 2; i++) w8[4*i +: 4] = el[i];
    endfunction

    // 7) 回避策: ローカルに組んでから全体代入
    function void pack_via_local();
      bit [135:0] t;
      foreach (el[i]) t[4*i +: 4] = el[i];
      w136 = t;
    endfunction

    // PART C 用: 全体代入と部分代入を混ぜ、内部から見た値も表示する
    function void mixed(output bit [31:0] seen_inside);
      w32[3:0] = 4'h1;
      w32[7:4] = 4'h2;
      w32      = 32'hDEAD_BEEF;
      w32[3:0] = 4'h5;
      seen_inside = w32;
    endfunction
  endclass

  C c;
  bit [135:0] lp;
  bit [31:0]  seen_val;
  bit [3:0]   ea [8];      // 対照用にコピーした要素配列

  // 関数ローカル変数への部分代入 (対照)
  function automatic bit [135:0] local_pack(input bit [3:0] e [8]);
    bit [135:0] t;
    foreach (e[i]) t[4*i +: 4] = e[i];
    return t;
  endfunction

  // モジュール変数への部分代入 (対照)
  bit [135:0] m136;

  initial begin
    c = new();
    c.fill_elems();

    $display("--- PART A: class method vs. others ---");

    c.w136 = '0; c.pack_foreach();
    chk("1) method / foreach part-select", c.w136, 136'h87654321);

    c.w136 = '0; c.pack_const();
    chk("2) method / const part-select x3", c.w136, 136'h321);

    c.w136 = '0; c.pack_bits();
    chk("3) method / bit-select x8",        c.w136, 136'hff);

    c.w136 = '0; c.pack_task();
    chk("4) method / task",                 c.w136, 136'h87654321);

    c.w136 = '0; c.pack_this();
    chk("5) method / this. explicit",       c.w136, 136'h87654321);

    c.w32 = '0; c.pack32();
    chk("6) method / 32bit property",       {104'h0, c.w32}, 136'h87654321);

    c.w8 = '0; c.pack8();
    chk("7) method / 8bit property",        {128'h0, c.w8},  136'h21);

    // 対照 1: モジュール変数
    ea   = c.el;
    m136 = '0;
    foreach (ea[i]) m136[4*i +: 4] = ea[i];
    chk("8) module variable (control)",     m136, 136'h87654321);

    // 対照 2: 関数ローカル変数
    lp = local_pack(ea);
    chk("9) function local  (control)",     lp,   136'h87654321);

    // 対照 3: クラス外からプロパティへ部分代入
    c.w136 = '0;
    foreach (ea[i]) c.w136[4*i +: 4] = ea[i];
    chk("10) property from outside (ctrl)", c.w136, 136'h87654321);

    // 回避策
    c.w136 = '0; c.pack_via_local();
    chk("11) workaround: local then assign", c.w136, 136'h87654321);

    $display("--- PART B: full assignment re-arms the first part-select ---");
    // メソッド内で「全体代入 -> 部分代入」を繰り返すと、部分代入は毎回
    // 1 回だけ効く。この規則性が症状の特定に効く。
    c.w32 = '0;
    c.mixed(seen_val);
    chk("12) mixed: value seen inside",     {104'h0, seen_val}, 136'hdeadbee5);
    chk("13) mixed: value seen outside",    {104'h0, c.w32},  136'hdeadbee5);

    $display("--- PART C: second call to the same method ---");
    // 2 回目の呼び出しでは直前が部分代入なので、先頭の w32[3:0] が効かない
    c.mixed(seen_val);
    chk("14) 2nd call: seen inside",        {104'h0, seen_val}, 136'hdeadbee5);
    chk("15) 2nd call: seen outside",       {104'h0, c.w32},  136'hdeadbee5);

    $display("=====================================");
    $display(" class_prop_partsel_minimal : %0d checks, %0d failures", n_check, n_fail);
    if (n_fail == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
