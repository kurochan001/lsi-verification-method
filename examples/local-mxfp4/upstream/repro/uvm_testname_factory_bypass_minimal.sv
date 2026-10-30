// -----------------------------------------------------------------------------
// sukimasim Issue #1319 の最小再現 (自己チェック型)
//
//   症状: +UVM_TESTNAME=<name> の解決が UVM factory の registry を経由していない。
//         宣言されているクラスを名前で拾い、無ければ黙って何もせず正常終了する。
//         観測される面は 4 つあるが、根は 1 つ (registry の迂回)。
//
//         (a) factory へ登録していないクラスが生成・実行される。
//         (b) `virtual class` (abstract class) まで構築され、全 phase を走る。
//         (c) 実装の無い pure virtual メソッドが呼ばれても黙って戻る。
//         (d) **存在しない名前を与えても UVM_ERROR も UVM_FATAL も出ず、
//             コンポーネントを 1 つも作らないまま "TEST PASSED" で終わる。**
//
//   期待動作:
//     - IEEE 1800.2-2020 §8.3.1.5 (create_component_by_name):
//         "When requesting by name, request_type_name is a string representing
//          the requested type, which shall have been registered with the factory
//          with that name prior to the request. If the factory does not recognize
//          the requested_type_name, an error shall be generated and a null handle
//          returned."
//     - IEEE 1800.2-2020 §F.7.3.1 (run_test) 手順 f):
//         "If no components other than uvm_root have been created at this point,
//          either by run_test or by the user, then an implementation shall
//          generate a fatal message and run_test shall return immediately."
//       -> 未登録・不存在の名前を与えたら UVM_ERROR + UVM_FATAL で即座に終わる。
//     - IEEE 1800-2023 §8.21:
//         "An object of an abstract class shall not be constructed directly."
//       -> virtual class はそもそも構築されてはならない。
//
//   経路の特定: 直接 `new()` で abstract class を構築しようとすると sukimasim は
//         正しく拒否する (E999 NewVirtualClass)。Verilator 5.050 も同じく
//         "Illegal to call 'new' using an abstract virtual class 'X'
//          (IEEE 1800-2023 8.21)" で拒否する。
//         つまり言語フロントエンドは §8.21 を実装できており、
//         **UVM の testname 解決経路だけがそれを迂回している。**
//         起動バナーの "Found N UVM test class(es)" が **登録数ではなく宣言数**を
//         数えていることも同じ根を示す。本ファイルは uvm_test 派生を 4 つ宣言し、
//         `uvm_component_utils` で登録しているのは 2 つ (reg_plain_test /
//         concrete_child_test) だけだが、バナーは "Found 4" と報告する。
//
//   実行 (5 ケースを別々に走らせる):
//     sukimasim --enable-uvm -top tb_uvm_testname_factory_bypass \
//       +UVM_TESTNAME=<name> --max-time 1us <this file>
//
//     <name> = reg_plain_test        ケース A
//              unreg_plain_test      ケース B
//              no_such_test_at_all   ケース C
//              unreg_abstract_test   ケース D
//              concrete_child_test   ケース E
//
//   **合格の形はケースごとに違う** (将来この回帰を読む人向け):
//     ケース A / E   … テストが走り、末尾に "*** PASS ***" が出る。
//     ケース B / C / D … テストが走ってはいけない。適合実装では
//                      UVM_ERROR (factory が名前を知らない) に続いて UVM_FATAL が
//                      出てシミュレーションが終わり、**"[FAIL]" 行が 1 つも
//                      出ないこと**が合格。"[FAIL] ..." が出たらそれが不具合の証拠。
//                      ケース C は何も表示されずに正常終了することそのものが
//                      不具合なので、判定はログに UVM_FATAL があるかで行う
//                      (下の「ケース C の判定」を参照)。
//                      fatal で終わると exit code は非ゼロになるため、
//                      Makefile では行頭 '-' で許容している。
//
//   ケース C の判定: 適合実装なら
//       UVM_ERROR ... factory does not recognize 'no_such_test_at_all'
//       UVM_FATAL ... no components were created
//     が出る。sukimasim (2026-08-20 ビルド) は 2 行とも出さず
//     "Running test no_such_test_at_all..." の後 "TEST PASSED" で終わる。
//
//   Verilator は UVM を実行できないため対照は取れない。上記のとおり
//   §8.21 の部分だけは純 SV に落として両シミュレータで確認済み。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_uvm_testname_factory_bypass;

  import uvm_pkg::*;
`include "uvm_macros.svh"

  // ---------------------------------------------------------------------------
  // ケース A: factory へ登録した通常のテスト (対照)
  //   これは走らなければならない。
  // ---------------------------------------------------------------------------
  class reg_plain_test extends uvm_test;
    `uvm_component_utils(reg_plain_test)

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #10;
      $display("[ ok ] A: registered non-virtual test ran (control)");
      $display("=====================================");
      $display(" uvm_testname_factory_bypass : case A");
      $display(" *** PASS ***");
      $display("=====================================");
      phase.drop_objection(this);
    endtask
  endclass

  // ---------------------------------------------------------------------------
  // ケース B: factory へ登録していない非 virtual クラス
  //   `uvm_component_utils` が無いので factory は名前を知らない。
  //   §8.3.1.5 より error + null、§F.7.3.1 f) より fatal。
  //   ここへ到達したら「virtual かどうかとは無関係に registry を引いていない」証拠。
  // ---------------------------------------------------------------------------
  class unreg_plain_test extends uvm_test;
    // 意図的に `uvm_component_utils` を書かない

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #10;
      $display("[FAIL] B: an UNREGISTERED test was created and run");
      $display("       IEEE 1800.2-2020 8.3.1.5 requires an error + null handle");
      $display("       for a type name the factory does not recognize, and");
      $display("       F.7.3.1 f) then requires a fatal from run_test().");
      phase.drop_objection(this);
    endtask
  endclass

  // ---------------------------------------------------------------------------
  // ケース D: factory へ登録していない virtual class (abstract class)
  //   実プロジェクトで踏んだ形 (mxfp4 の mxfp4_seq_test)。
  //   §8.21 より構築自体が違法。pure virtual の実装も無い。
  //
  //   ケース E の基底も兼ねるので、run_phase は派生側で上書きする。
  //   したがってこの run_phase が走るのは「基底そのものが構築されたとき」に限る。
  // ---------------------------------------------------------------------------
  virtual class unreg_abstract_test extends uvm_test;
    // 意図的に `uvm_component_utils` を書かない (abstract なので登録もできない)

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    pure virtual task body_impl();

    virtual task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #10;
      $display("[FAIL] D: an UNREGISTERED ABSTRACT (virtual) class was constructed");
      $display("       IEEE 1800-2023 8.21: an object of an abstract class shall");
      $display("       not be constructed directly.");
      body_impl();          // 実装が無い pure virtual。呼べてしまうこと自体が異常
      $display("[FAIL] D: a pure virtual task with no implementation returned silently");
      phase.drop_objection(this);
    endtask
  endclass

  // ---------------------------------------------------------------------------
  // ケース E: 上の abstract 基底を継承した具象クラス (対照)
  //   これは正当に登録でき、走らなければならない。
  //   基底が「派生させるための abstract」という正当な形であることも示す。
  // ---------------------------------------------------------------------------
  class concrete_child_test extends unreg_abstract_test;
    `uvm_component_utils(concrete_child_test)

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    task body_impl();
      $display("[ ok ] E: concrete_child_test::body_impl() ran");
    endtask

    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #10;
      $display("[ ok ] E: registered concrete child of the abstract base ran (control)");
      body_impl();
      $display("=====================================");
      $display(" uvm_testname_factory_bypass : case E");
      $display(" *** PASS ***");
      $display("=====================================");
      phase.drop_objection(this);
    endtask
  endclass

  initial begin
    run_test();
  end

endmodule
