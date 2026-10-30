// -----------------------------------------------------------------------------
// sukimasim Issue #1320 の最小再現 (自己チェック型)
//
//   症状: interface の **unpacked 配列**メンバが、接続先モジュールの
//         **formal ポート名と同じ綴り**のとき、その配列の記憶域が壊れる。
//         面は 2 つあるが、根は 1 つ (綴りの衝突)。
//
//         (a) 配列要素へのノンブロッキング代入が無言で捨てられる
//             (ブロッキング代入は届く)。
//         (b) 同じ formal 名へ繋いだ**無関係な別インスタンスの actual** と
//             記憶域を共有する。片方へ書くともう片方が変わる。
//
//   双子の作り方: 本ファイルは `+define+RENAMED` で interface メンバの綴りだけを
//   `a` -> `arr` に変える。**変わるのはその 1 語だけ**で、接続も検査も同一。
//     既定 (同綴り)      : sukimasim は 4 checks 中 3 つ失敗
//     +define+RENAMED    : sukimasim も 4 checks / 0 failures
//   対照の Verilator 5.050 はどちらの版も 0 failures。
//
//   **注意: このバグはインスタンスを足すと隠れる。** 同じ検査を別のインスタンス群と
//   同居させると症状が出なくなるので、再現は必ずこの最小構成のまま走らせること。
//
//   期待動作:
//     - IEEE 1800-2023 §10.4.2: ノンブロッキング代入は NBA 領域で左辺を更新する。
//       左辺が interface のメンバか、ポートへ接続されているか、formal と同綴りかは
//       関係しない。
//     - §23.3.3 のポート接続は actual と formal を結び付けるだけで、
//       無関係な別インスタンスの actual 同士を結び付けることはない。
//
//   影響: interface のメンバ名を接続先の信号名と揃えるのは普通の書き方なので、
//         素直に書くと踏む。本プロジェクトでは `enc_if` の `v_i` /
//         `e_rel_dbg` / `mag3_dbg` / `tie_hit_dbg` が `quant_encoder` の
//         同名ポートへ繋がる。**packed 信号は同綴りでも壊れない**ので、
//         全メンバが packed の `bdp_if` (BDP 用) は無事だった。
//
//   実行:
//     sukimasim -top tb_if_unpacked_port_name_clash <this file>
//     sukimasim -top tb_if_unpacked_port_name_clash +define+RENAMED <this file>
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

`ifdef RENAMED
  `define ARRNAME arr
`else
  `define ARRNAME a
`endif

interface u_if (input logic clk);
  // 既定では snoop の formal 'a' と同綴り。+define+RENAMED で 'arr' になる。
  logic [31:0] `ARRNAME [4];
endinterface

module snoop (
  input  logic        clk,
  input  logic [31:0] a [4],       // formal 名は常に 'a'
  output logic [31:0] o [4]
);
  always_ff @(posedge clk) for (int i = 0; i < 4; i++) o[i] <= a[i];
endmodule

module clkgen (output logic clk);
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end
endmodule

module tb_if_unpacked_port_name_clash;

  logic clk;
  clkgen u_c (.clk(clk));

  u_if ui (clk);
  logic [31:0] ms [4];             // interface とは無関係な module スコープ配列

  logic [31:0] o_if [4];
  logic [31:0] o_ms [4];

  snoop u_if_inst (.clk(clk), .a(ui.`ARRNAME), .o(o_if));
  snoop u_ms_inst (.clk(clk), .a(ms),          .o(o_ms));

  int checks = 0, errors = 0;

  task automatic chk(input string name, input logic [31:0] got, input logic [31:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      $display("[FAIL] %-50s got=%08h exp=%08h", name, got, exp);
    end else begin
      $display("[ ok ] %-50s = %08h", name, got);
    end
  endtask

  initial begin
    for (int i = 0; i < 4; i++) begin
      ui.`ARRNAME[i] = 32'h11111111;
      ms[i]          = 32'h22222222;
    end
    repeat (2) @(negedge clk);

    // --- 面 (a): 要素への NBA が届くか ---
    @(negedge clk); ui.`ARRNAME[0] <= 32'h50;
    @(negedge clk);
    chk("(a) NBA landed in the interface array", ui.`ARRNAME[0], 32'h50);
    @(posedge clk); #1;
    chk("(a) DUT saw it through the port",       o_if[0],        32'h50);

    // --- 面 (b): 無関係な配列と記憶域を共有していないか ---
    for (int i = 0; i < 4; i++) ui.`ARRNAME[i] = 32'h11111111;
    @(negedge clk);
    for (int i = 0; i < 4; i++) ms[i] = 32'h90 + i;     // ms にだけ書く
    @(negedge clk);
    chk("(b) ms[3] holds what we wrote",         ms[3],          32'h93);
    chk("(b) interface array must be UNTOUCHED", ui.`ARRNAME[3], 32'h11111111);

    $display("=====================================");
`ifdef RENAMED
    $display(" if_unpacked_port_name_clash (RENAMED, control) : %0d checks, %0d errors",
             checks, errors);
`else
    $display(" if_unpacked_port_name_clash (name clash)       : %0d checks, %0d errors",
             checks, errors);
`endif
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
