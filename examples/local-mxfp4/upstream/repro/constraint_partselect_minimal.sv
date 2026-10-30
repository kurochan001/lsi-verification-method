// -----------------------------------------------------------------------------
// 幅の広い rand 変数の part-select 等式制約 + inline 制約で randomize() が失敗する
//   — 最小再現
//
//   対象: sukimasim
//   規格: IEEE 1800-2023 §18.5 (Constraint blocks) / §18.7 (In-line constraints)
//
//   解は自明に存在する (例: sc = 100、blk[135:128] = 100、残りは任意) が、
//   sukimasim の制約ソルバは試行回数で打ち切って failure を返す:
//     [WARNING] Constraint solver timeout after ~2100 attempts
//               (hard constraints only, treating as failure)
//
//   PART A が本題。PART B〜D は切り分け用で、いずれも成功する。
//
//   実行 (行頭を $ にしているのは、行頭の "verilator" が BADVLTPRAGMA になるため):
//     $ sukimasim -top tb_constraint_partselect <this file>
//     $ verilator --binary --timing --timescale 1ns/1ps \
//         --top-module tb_constraint_partselect <this file>
//
//   期待値 (Verilator 5.048 はこうなる): 4 項目すべて 10/10
// -----------------------------------------------------------------------------
//   [切り分け結果 2026-08-10]
//
//   変数幅を振ると 68bit までは解け、69bit 以上で解けなくなる:
//       w=16/24/32/40/48/64/65/66/68 -> OK      w=69/70/71/72/96/128/136 -> NG
//
//   part-select の位置も効く (幅 136bit 固定):
//       blk[7:0]     (下位 64bit ワード内) -> OK
//       blk[71:64]                        -> NG
//       blk[135:128]                      -> NG
//
//   inline 制約を外すと幅によらず解ける。inline の種類 (inside / 等式) は無関係。
//   すなわち「幅の広い rand 変数に part-select の等式制約があり、かつ inline 制約が
//   付いたとき」に限って失敗する。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

// PART A: 本題 (136bit の上位 8bit に等式制約 + inline 制約)
class m_wide;
  rand bit [135:0] blk;
  rand bit [7:0]   sc;
  constraint c_pack { blk[135:128] == sc; }
endclass

// PART B: 同じ形だが inline 制約なし
class m_wide_b;
  rand bit [135:0] blk;
  rand bit [7:0]   sc;
  constraint c_pack { blk[135:128] == sc; }
endclass

// PART C: 幅を 64bit に落としたもの
class m_narrow;
  rand bit [63:0] blk;
  rand bit [7:0]  sc;
  constraint c_pack { blk[63:56] == sc; }
endclass

// PART D: 幅は 136bit のまま、part-select を下位 64bit ワード内にしたもの
class m_wide_lo;
  rand bit [135:0] blk;
  rand bit [7:0]   sc;
  constraint c_pack { blk[7:0] == sc; }
endclass

module tb_constraint_partselect;
  initial begin
    automatic m_wide    a = new();
    automatic m_wide_b  b = new();
    automatic m_narrow  c = new();
    automatic m_wide_lo d = new();
    automatic int ok_a = 0, ok_b = 0, ok_c = 0, ok_d = 0;
    automatic int bad = 0;

    // --- PART A: 136bit + part-select 等式 + inline (失敗する) ---
    for (int k = 0; k < 10; k++)
      if (a.randomize() with { sc inside {[8'd7 : 8'd247]}; }) begin
        ok_a++;
        if (a.blk[135:128] !== a.sc) bad++;                 // 制約充足の確認
        if (!(a.sc inside {[8'd7:8'd247]}))  bad++;
      end

    // --- PART B: inline なし ---
    for (int k = 0; k < 10; k++) if (b.randomize()) ok_b++;

    // --- PART C: 幅 64bit ---
    for (int k = 0; k < 10; k++)
      if (c.randomize() with { sc inside {[8'd7 : 8'd247]}; }) ok_c++;

    // --- PART D: part-select が下位 64bit ワード内 ---
    for (int k = 0; k < 10; k++)
      if (d.randomize() with { sc inside {[8'd7 : 8'd247]}; }) ok_d++;

    $display("PART A  136bit, blk[135:128]==sc, inline : %0d/10 (expected 10)", ok_a);
    $display("PART B  136bit, same constraint, no inline: %0d/10 (expected 10)", ok_b);
    $display("PART C   64bit, blk[63:56]==sc,   inline : %0d/10 (expected 10)", ok_c);
    $display("PART D  136bit, blk[7:0]==sc,     inline : %0d/10 (expected 10)", ok_d);
    $display("constraint violations among successes    : %0d (expected 0)", bad);
    if (ok_a == 10 && ok_b == 10 && ok_c == 10 && ok_d == 10 && bad == 0)
      $display("*** PASS ***");
    else
      $display("*** FAIL ***");
    $finish;
  end
endmodule
