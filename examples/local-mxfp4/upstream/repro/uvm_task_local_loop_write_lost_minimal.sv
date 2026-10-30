// -----------------------------------------------------------------------------
// sukimasim Issue #1322 の最小再現 (自己チェック型)
//
//   症状: UVM コンポーネントのタスク内で、**`if` ブロックの中の `for` ループが
//         ローカル変数へ書いた値が失われる。** 同じブロックに
//         **クラスハンドル経由のメソッド呼び出し**があるときだけ起きる。
//         ループ直後に読み返しても書いた値が入っておらず、ゼロが返る。
//
//   4 つの条件がすべて揃ったときだけ再現する。1 つでも外すと消える:
//     (1) 書き込みが `for` ループの中にある      (1 文にすると消える → ケース C)
//     (2) その `for` が `if (...) begin ... end` の中にある (外すと消える → D)
//     (3) 同じブロックにクラスハンドル経由のメソッド呼び出しがある
//         (呼び出しを外すと消える → B。`$sformatf()` のような
//          ハンドルを介さない呼び出しでは再現しない)
//     (4) タスクが UVM コンポーネントのメソッドで、run phase から呼ばれる
//   メソッド呼び出しの位置はループの前でも後でもよい (順序ではなく存在が効く)。
//   `automatic` を明示しても変わらない。ローカルが配列でもスカラでも起きる。
//   ハンドルの生成は `new()` でも `type_id::create()` でも起きる。
//
//   期待動作: IEEE 1800-2023 §6.21 は automatic 変数に「呼び出しごとの新しい
//     コピー」を与えると規定し、§13.3.1 は「automatic task 内で宣言された項目は
//     呼び出しごとに動的に確保される」と定める。クラスのメソッドは §8.6 により
//     既定で automatic であり、同じ活性化の中で別オブジェクトのメソッドを
//     呼んだかどうかがローカルの値に影響してはならない。
//
//   影響: **黙って壊れる。** UVM の monitor でよくある形
//     (`if (valid) begin ... for (...) collect; ap.write(tr); end`) がそのまま
//     該当する。トランザクションが全ゼロになり、参照モデルも同じ入力から
//     全ゼロを計算するため、**スコアボードが vacuous に一致して通る**。
//     実際に踏んだときは、機能カバレッジが伸びないことだけが手掛かりだった。
//
//   対照は Verilator では取れない (UVM 非対応)。代わりに同じ 4 条件を
//   UVM 抜きのプレーンなクラスで書くと sukimasim でも正しく動くので、
//   条件 (4) が要ることは確認済み。
//
//   実行: sukimasim --enable-uvm -top tb_uvm_task_local -assert \
//           +UVM_TESTNAME=chk_test <this file>
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

package tl_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  // 呼び出す相手。中身は何でもよい
  class helper extends uvm_object;
    `uvm_object_utils(helper)
    function new(string name = "helper"); super.new(name); endfunction
  endclass

  class chk_mon extends uvm_monitor;
    `uvm_component_utils(chk_mon)

    bit [31:0] got_a, got_b, got_c, got_d;
    int checks, errors;

    function new(string name, uvm_component parent);
      super.new(name, parent);
      checks = 0; errors = 0;
    endfunction

    // A: 4 条件がそろった形
    task t_a();
      helper h;
      bit [31:0] loc [2];
      if (1'b1) begin
        h = new();
        for (int i = 0; i < 2; i++) loc[i] = 32'hAAAA0001;
        got_a = loc[0];
        void'(h.get_name());
      end
    endtask

    // B (対照): ハンドル経由のメソッド呼び出しを外す
    task t_b();
      helper h;
      bit [31:0] loc [2];
      if (1'b1) begin
        h = new();
        for (int i = 0; i < 2; i++) loc[i] = 32'hAAAA0002;
        got_b = loc[0];
      end
    endtask

    // C (対照): for ループでなく 1 文で書く
    task t_c();
      helper h;
      bit [31:0] loc [2];
      if (1'b1) begin
        h = new();
        loc[0] = 32'hAAAA0003;
        got_c = loc[0];
        void'(h.get_name());
      end
    endtask

    // D (対照): if ブロックに入れない
    task t_d();
      helper h;
      bit [31:0] loc [2];
      h = new();
      for (int i = 0; i < 2; i++) loc[i] = 32'hAAAA0004;
      got_d = loc[0];
      void'(h.get_name());
    endtask

    task run_phase(uvm_phase phase);
      #20;
      t_a();
      t_b();
      t_c();
      t_d();
    endtask

    function void chk(input string name, input bit [31:0] got, input bit [31:0] exp);
      checks++;
      if (got !== exp) begin
        errors++;
        $display("[FAIL] %-52s got=%08h exp=%08h", name, got, exp);
      end else begin
        $display("[ ok ] %-52s = %08h", name, got);
      end
    endfunction

    function void report_phase(uvm_phase phase);
      chk("A if + for + a method call through a handle", got_a, 32'hAAAA0001);
      chk("B same, without the method call        [control]", got_b, 32'hAAAA0002);
      chk("C same, a single statement not a for   [control]", got_c, 32'hAAAA0003);
      chk("D same, outside the if block           [control]", got_d, 32'hAAAA0004);
      $display("=====================================");
      $display(" uvm_task_local_loop_write_lost : %0d checks, %0d errors", checks, errors);
      if (errors == 0) $display(" *** PASS ***");
      else             $display(" *** FAIL ***");
      $display("=====================================");
    endfunction
  endclass

  class chk_test extends uvm_test;
    `uvm_component_utils(chk_test)
    chk_mon mon;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      mon = chk_mon::type_id::create("mon", this);
    endfunction
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #200;
      phase.drop_objection(this);
    endtask
  endclass
endpackage

// クロック生成はサブモジュールへ (Issue #1176 の運用。本件とは無関係)
module tl_clkgen (output logic clk);
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end
endmodule

module tb_uvm_task_local;
  import uvm_pkg::*;
  import tl_pkg::*;
  logic clk;
  tl_clkgen u_c (.clk(clk));
  initial begin
    run_test();
  end
endmodule
