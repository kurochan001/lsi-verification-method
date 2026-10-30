// -----------------------------------------------------------------------------
// clocking block イベント @(vif.cb) が、同じクロックを待つ他のプロセスが
// いると 1 回しかトリガされない — 最小再現
//
//   対象: sukimasim 0.9.9.2 (Issue #1171)
//   規格: IEEE 1800-2023 §14.11 (Clocking block events)、§9.4.2 (Event control)
//
//   LRM の規定:
//     "The clocking event of a clocking block can be used to synchronize with
//      the clocking block ... @(clocking_block_identifier) is equivalent to
//      @(clocking_block_identifier's clocking event)."
//     クロッキングイベントは通常のイベント制御と同じく、待っているすべての
//     プロセスを毎回起こす。待ち手の数や、同じクロックを待つ別プロセスの
//     有無で挙動が変わってはならない。
//
//   観測される症状 (sukimasim 0.9.9.2):
//     同じクロックを virtual interface 経由の @(posedge vif.clk) で待つ
//     プロセスが並走していると、@(vif.cb) / @(vif.cb_mon) を forever で待つ
//     プロセスは最初の 1 回しかトリガされず以後止まる (PART C)。
//     clocking block だけを複数プロセスが待つ場合 (PART B) は正しく動くので、
//     条件は「素の posedge 待ちとの共存」である。
//     素の @(posedge vif.clk) 側は影響を受けない (PART C の control)。
//
//   実務上の影響:
//     UVM の driver / monitor は clocking block 経由でハンドシェイクするのが
//     定石であり、同一クロックを待つプロセスは必ず複数になる。結果として
//     driver が 1 サイクルしか駆動せず、monitor が何も観測しないまま
//     テストが「0 件比較で PASS」に見える状態になる。
//
//   回避策:
//     clocking block を使わず、素の信号を negedge でブロッキング駆動し
//     posedge でサンプルする (プレーン SV の古典的な書き方)。
//
//   実行 (行頭に "verilator" を置くと BADVLTPRAGMA になるため $ で始める):
//     $ sukimasim -top tb_clocking_event clocking_event_minimal.sv
//     $ verilator --binary --timing --timescale 1ns/1ps \
//         --top-module tb_clocking_event clocking_event_minimal.sv
//
//   期待値 (Verilator 5.048 はこうなる): n_fail = 0
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

interface ck_if (input logic clk);
  logic [7:0] data;

  clocking cb @(posedge clk);
    default input #1step output #1;
    output data;
  endclocking

  clocking cb_mon @(posedge clk);
    default input #1step;
    input data;
  endclocking
endinterface

module tb_clocking_event;

  localparam int NCYC = 10;

  logic clk;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  ck_if i0(clk);

  int n_check = 0;
  int n_fail  = 0;

  // 起動タイミングの差で 1 回多く数える処理系があるため、下限で判定する。
  // 症状は「最初の 1 回で止まる」なので、下限判定でも十分に区別できる。
  function automatic void chk(input string nm, input int got, input int exp);
    n_check++;
    if (got < exp) begin
      n_fail++;
      $display("[FAIL] %-44s got=%0d exp>=%0d", nm, got, exp);
    end else begin
      $display("[ ok ] %-44s got=%0d", nm, got);
    end
  endfunction

  // ---------------------------------------------------------------------------
  // 待ち手クラス
  // ---------------------------------------------------------------------------
  class Waiter;
    virtual ck_if vif;
    int n_cb, n_cbmon, n_pos;

    task wait_cb();     forever begin @(vif.cb);          n_cb++;    end endtask
    task wait_cbmon();  forever begin @(vif.cb_mon);      n_cbmon++; end endtask
    task wait_pos();    forever begin @(posedge vif.clk); n_pos++;   end endtask
  endclass

  Waiter wa, wb, wc, wd;

  initial begin
    wa = new(); wa.vif = i0;
    wb = new(); wb.vif = i0;
    wc = new(); wc.vif = i0;
    wd = new(); wd.vif = i0;
    i0.data = 8'h0;

    // --- PART A: cb を待つプロセスが 1 本だけ (posedge の待ち手なし) ---
    fork wa.wait_cb(); join_none
    repeat (NCYC) @(posedge clk);
    #1;
    chk("A) cb alone", wa.n_cb, NCYC);

    // --- PART B: 同じ clocking block を 3 本が待つ ---
    fork wb.wait_cb(); join_none
    fork wc.wait_cb(); join_none
    fork wd.wait_cb(); join_none
    repeat (NCYC) @(posedge clk);
    #1;
    chk("B) same cb, waiter 1 of 3", wb.n_cb, NCYC);
    chk("B) same cb, waiter 2 of 3", wc.n_cb, NCYC);
    chk("B) same cb, waiter 3 of 3", wd.n_cb, NCYC);

    // --- PART C: cb_mon と @(posedge vif.clk) の共存 ---
    //   posedge を待つプロセスがいると、clocking block 側の待ちが止まる。
    fork wa.wait_pos();   join_none
    fork wa.wait_cbmon(); join_none
    repeat (NCYC) @(posedge clk);
    #1;
    chk("C) posedge waiter (control)", wa.n_pos,   NCYC);
    chk("C) cb_mon waiter coexisting", wa.n_cbmon, NCYC);

    $display("=====================================");
    $display(" clocking_event_minimal : %0d checks, %0d failures", n_check, n_fail);
    if (n_fail == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
