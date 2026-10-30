// -----------------------------------------------------------------------------
// sukimasim Issue #1176 の最小再現 (自己チェック型)
//
//   症状: UVM の run phase で objection が 0 になった瞬間に、
//         (A) run_test() を呼んだモジュール自身に属する静的プロセス
//             (initial / always / そこから fork した子) がすべて kill される。
//             サブモジュールに属するプロセスは kill されない。
//         (B) 設計側の continuous assign が再評価されなくなる。
//             always_ff は動き続けるので、レジスタは進むのに assign 出力だけが
//             凍結し、drain time 中の観測値が黙って壊れる。
//
//   期待動作: objection の drop は phase の終了条件を満たすだけであり
//         (IEEE 1800.2-2020 §9.4.2)、静的プロセスの終了や設計の評価停止とは
//         無関係。drain time 中もクロックは回り、設計は正しく評価され続ける。
//         drain time は「パイプラインを吐き出させるための猶予」なので、
//         そこで設計が止まると存在意義が無くなる。
//
//   影響: モジュールトップにクロック生成を置く一般的な UVM 環境がすべて壊れる。
//         drain time 中にクロックが止まり、パイプラインが結果を出せない。
//         さらに (B) により valid 系の assign が凍結するため、
//         「out_valid が一度も立たない」という形で照合が全滅する。
//
//   Verilator は UVM を実行できないため対照は取れない。代わりに同じ設計を
//   UVM なしのプレーン SV で駆動すると両方とも正しく動くことを確認済み。
//
//   実行: sukimasim --enable-uvm -top tb_uvm_objection_drop_teardown <this file>
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

// -----------------------------------------------------------------------------
// PART A 用: run_test() を呼ばないモジュールに置いたプロセス (生存するはず)
// -----------------------------------------------------------------------------
module alive_sub (output int n_tick);
  initial begin
    n_tick = 0;
    forever begin
      #10;
      n_tick++;
    end
  end
endmodule

// -----------------------------------------------------------------------------
// PART B 用: always_ff で進むカウンタと、それを見る continuous assign
// -----------------------------------------------------------------------------
module cnt_dut (
  input  logic       clk,
  input  logic       rst_n,
  output logic [7:0] q,
  output logic       flag,       // continuous assign。q >= 10 (drop より後に変化)
  output logic       flag_ac,    // 同じ式を always_comb で書いた対照
  output logic       flag_early  // continuous assign。q >= 3 (drop より前に変化)
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) q <= 8'd0;
    else        q <= q + 8'd1;
  end
  assign flag       = (q >= 8'd10);
  assign flag_early = (q >= 8'd3);
  always_comb flag_ac = (q >= 8'd10);
endmodule

// クロック生成もサブモジュールに置く (PART A の kill を避けて PART B を観測する)
module clkgen (output logic clk);
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end
endmodule

// PART B の照合。サブモジュールに置くので objection drop 後も生き残る。
module flag_checker (input logic clk, input logic rst_n, input logic [7:0] q,
                     input logic flag, input logic flag_ac, input logic flag_early);
  int n_chk, n_bad, n_bad_ac, n_bad_early;
  initial begin
    n_chk       = 0;
    n_bad       = 0;
    n_bad_ac    = 0;
    n_bad_early = 0;
    forever begin
      @(posedge clk);
      #1;
      if (rst_n === 1'b1) begin
        n_chk++;
        if (flag !== (q >= 8'd10)) begin
          if (n_bad < 3)
            $display("[assign]      t=%0t  q=%0d flag=%b (期待 %b)",
                     $time, q, flag, (q >= 8'd10));
          n_bad++;
        end
        if (flag_ac !== (q >= 8'd10)) begin
          if (n_bad_ac < 3)
            $display("[always_comb] t=%0t  q=%0d flag_ac=%b (期待 %b)",
                     $time, q, flag_ac, (q >= 8'd10));
          n_bad_ac++;
        end
        if (flag_early !== (q >= 8'd3)) n_bad_early++;
      end
    end
  end
endmodule

// -----------------------------------------------------------------------------
module tb_uvm_objection_drop_teardown;
  import uvm_pkg::*;
`include "uvm_macros.svh"

  logic clk, rst_n;
  logic [7:0] q;
  logic       flag, flag_ac, flag_early;

  clkgen  u_clk (.clk(clk));
  cnt_dut u_dut (.clk(clk), .rst_n(rst_n), .q(q),
                 .flag(flag), .flag_ac(flag_ac), .flag_early(flag_early));
  flag_checker u_chk (.clk(clk), .rst_n(rst_n), .q(q),
                      .flag(flag), .flag_ac(flag_ac), .flag_early(flag_early));

  // ---------------------------------------------------------------------------
  // PART A: プロセスの生存確認
  // ---------------------------------------------------------------------------
  int n_sub;
  alive_sub u_sub (.n_tick(n_sub));

  int n_top_initial, n_top_always, n_top_fork;

  initial begin
    n_top_initial = 0;
    forever begin
      #10;
      n_top_initial++;
    end
  end

  initial n_top_always = 0;
  always begin
    #10;
    n_top_always++;
  end

  initial begin
    n_top_fork = 0;
    fork
      forever begin
        #10;
        n_top_fork++;
      end
    join_none
  end

  // リセット (drop 前に完了する)
  initial begin
    rst_n = 1'b1;
    #1 rst_n = 1'b0;
    #14 rst_n = 1'b1;
  end

  // ---------------------------------------------------------------------------
  // objection を 55ns で drop し、drain time 200ns を与える。
  //   q が 10 に達するのは t=115ns なので、drop 後に flag が 0 -> 1 へ
  //   変化しなければならない。
  // ---------------------------------------------------------------------------
  class drop_test extends uvm_test;
    `uvm_component_utils(drop_test)
    function new(string n, uvm_component p); super.new(n, p); endfunction
    function void end_of_elaboration_phase(uvm_phase phase);
      uvm_phase rp;
      rp = uvm_run_phase::get();
      rp.phase_done.set_drain_time(this, 200ns);
    endfunction
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #55;
      phase.drop_objection(this);
    endtask
  endclass

  initial run_test("drop_test");

  // ---------------------------------------------------------------------------
  // 集計。サブモジュール側から呼ばれる形にはできないので、
  // ここも kill される可能性がある。そのため drop 前 (t=50) に基準値を取り、
  // 最終判定は checker/alive_sub の値を final_phase で読む。
  // ---------------------------------------------------------------------------
  int base_top_initial, base_top_always, base_top_fork, base_sub;
  initial begin
    #50;
    base_top_initial = n_top_initial;
    base_top_always  = n_top_always;
    base_top_fork    = n_top_fork;
    base_sub         = n_sub;
  end

  final begin
    int n_fail;
    n_fail = 0;
    $display("");
    $display("--- PART A: objection drop (t=55ns) 後もプロセスが生きているか ---");
    $display("  t=50ns 時点   : top-initial=%0d top-always=%0d top-fork=%0d submodule=%0d",
             base_top_initial, base_top_always, base_top_fork, base_sub);
    $display("  終了時点      : top-initial=%0d top-always=%0d top-fork=%0d submodule=%0d",
             n_top_initial, n_top_always, n_top_fork, n_sub);
    // すべて同じ #10 のループなので、生きていれば最後は同じ回数になる。
    // サブモジュール側を基準にして 1 回のずれまで許容する。
    if (n_sub <= base_sub) begin
      n_fail++;
      $display("[FAIL] サブモジュールの initial が drop 後に進んでいない");
    end else begin
      $display("[ ok ] サブモジュールの initial は生存 (基準)");
    end
    if (n_top_initial + 1 < n_sub) begin
      n_fail++;
      $display("[FAIL] run_test() を呼ぶモジュールの initial が drop で kill された (%0d / 基準 %0d)",
               n_top_initial, n_sub);
    end else $display("[ ok ] トップの initial は生存");
    if (n_top_always + 1 < n_sub) begin
      n_fail++;
      $display("[FAIL] run_test() を呼ぶモジュールの always が drop で kill された (%0d / 基準 %0d)",
               n_top_always, n_sub);
    end else $display("[ ok ] トップの always は生存");
    if (n_top_fork + 1 < n_sub) begin
      n_fail++;
      $display("[FAIL] トップから fork join_none した子が drop で kill された (%0d / 基準 %0d)",
               n_top_fork, n_sub);
    end else $display("[ ok ] トップの fork 子は生存");

    $display("");
    $display("--- PART B: drop 後も組合せ論理が再評価されるか ---");
    $display("  照合サイクル数=%0d  assign 不一致=%0d  always_comb 不一致=%0d",
             u_chk.n_chk, u_chk.n_bad, u_chk.n_bad_ac);
    if (u_chk.n_chk == 0) begin
      n_fail++;
      $display("[FAIL] 照合が 1 回も走っていない");
    end else begin
      // 対照: drop より前 (t=45ns) に変化する assign は正しく追従しているはず。
      // これが ok なら「assign 一般が壊れている」のではなく
      // 「drop の時点で組合せ評価が止まる」ことが示せる。
      if (u_chk.n_bad_early != 0) begin
        n_fail++;
        $display("[FAIL] drop より前に変化する assign も追従しない (%0d 件)",
                 u_chk.n_bad_early);
      end else $display("[ ok ] drop より前に変化する assign は正常 (対照)");
      if (u_chk.n_bad != 0) begin
        n_fail++;
        $display("[FAIL] assign flag = (q >= 10) が q に追従しない (drop 後に凍結)");
      end else $display("[ ok ] continuous assign は drop 後も追従");
      if (u_chk.n_bad_ac != 0) begin
        n_fail++;
        $display("[FAIL] always_comb も q に追従しない (drop 後に凍結)");
      end else $display("[ ok ] always_comb は drop 後も追従");
    end

    $display("=====================================");
    $display(" uvm_objection_drop_teardown_minimal : %0d failures", n_fail);
    if (n_fail == 0) $display(" *** PASS ***");
    else            $display(" *** FAIL ***");
    $display("=====================================");
  end
endmodule
