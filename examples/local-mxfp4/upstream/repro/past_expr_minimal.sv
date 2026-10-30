// -----------------------------------------------------------------------------
// $past の第 1 引数に「式」を渡すと 1 tick 余分に遅れる — 最小再現
//
//   対象: sukimasim (Issue #1164)
//   規格: IEEE 1800-2023 §16.9.3 Sampled value functions
//
//   LRM の規定:
//     "$past returns the sampled value of expression1 in a particular time step
//      strictly prior to the one in which $past is evaluated. If number_of_ticks
//      equals k ... the particular time step is the k-th strictly prior time step
//      in which the event ev iff expression2 occurred."
//     "expression1 and expression2 may be any expression allowed in assertions."
//
//   すなわち expression1 が式であっても、k 番目の strictly prior なティックでの
//   その式のサンプル値を返さなければならない。中間レジスタを挟む余地はない。
//
// -----------------------------------------------------------------------------
//   [状態 2026-08-10]
//     PART A (procedural context)         … 修正済み。n_mismatch = 0
//     PART B (concurrent assertion 内)    … 未修正。n_sva_fail > 0
//
//   Issue #1164 の修正は手続き文脈の $past にのみ適用されており、property の中で
//   評価される $past には及んでいない。切り分けの結果、次はいずれも無関係だった:
//     - clocking event の iff の有無
//     - 式の項数 (2 項 / 3 項)
//     - number_of_ticks がリテラルかパラメータか
//   決め手は「第 1 引数が式か単一信号か」だけである。
//
//   実行 (コマンドは行頭を $ で始めている。行頭に "verilator" を置くと
//   BADVLTPRAGMA で構文エラーになるため):
//     $ sukimasim -assert -top tb_past_expr_minimal past_expr_minimal.sv
//     $ verilator --binary --timing --assert --timescale 1ns/1ps \
//         --top-module tb_past_expr_minimal past_expr_minimal.sv
//
//   期待値 (Verilator 5.048 はこうなる): n_mismatch = 0 かつ n_sva_fail = 0
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

package past_repro_pkg;
  localparam int LAT = 6;
endpackage

// ---------------------------------------------------------------------------
// PART B 用の DUT: sig が tick T で立つと out は tick T+LAT で立つ
// ---------------------------------------------------------------------------
module dut_shift (
  input  logic clk,
  input  logic rst_n,
  input  logic vld,
  input  logic sig,
  output logic out
);
  import past_repro_pkg::*;
  logic [LAT-1:0] pipe;
  always @(posedge clk) begin
    if (!rst_n) pipe <= '0;
    else        pipe <= {pipe[LAT-2:0], vld & sig};
  end
  assign out = pipe[LAT-1];
endmodule

module tb_past_expr_minimal;

  import past_repro_pkg::*;

  logic clk, rst_n;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  // ===========================================================================
  // PART A: procedural context の $past  (Issue #1164 で修正済み)
  // ===========================================================================
  logic a, b;
  logic ab;
  assign ab = a && b;

  int n_mismatch = 0;

  always @(posedge clk) begin
    // 単一信号版と式版は常に一致しなければならない
    if ($past(ab, 1) !== $past(a && b, 1)) n_mismatch++;
    if ($past(ab, 3) !== $past(a && b, 3)) n_mismatch++;
  end

  // ===========================================================================
  // PART B: concurrent assertion 内の $past  (未修正)
  // ===========================================================================
  logic vld, sig, out;

  dut_shift u_dut (.clk(clk), .rst_n(rst_n), .vld(vld), .sig(sig), .out(out));

  logic vs;
  assign vs = vld && sig;

  int n_sva_mid = 0;    // 中間信号を渡す形   -> 0 になるべき (実際 0)
  int n_sva_fail = 0;   // 式を直接渡す形     -> 0 になるべき (sukimasim では非 0)

  // 参照: 中間信号を渡す形
  a_mid: assert property (@(posedge clk) disable iff (!rst_n) out |-> $past(vs, LAT))
    else n_sva_mid++;

  // 本題: 式を直接渡す形。LRM 上 a_mid と完全に等価でなければならない
  a_expr: assert property (@(posedge clk) disable iff (!rst_n) out |-> $past(vld && sig, LAT))
    else n_sva_fail++;

  // ===========================================================================
  // スティミュラス
  // ===========================================================================
  initial begin
    rst_n = 1'b0;
    a = 1'b0; b = 1'b0;
    vld = 1'b0; sig = 1'b0;
    repeat (3) @(negedge clk);
    rst_n = 1'b1;

    // --- PART A: ab が 1 になるのは 2 tick だけ ---
    @(negedge clk); a = 1'b1; b = 1'b1;
    @(negedge clk); a = 1'b1; b = 1'b0;
    @(negedge clk); a = 1'b0; b = 1'b1;
    @(negedge clk); a = 1'b1; b = 1'b1;
    @(negedge clk); a = 1'b0; b = 1'b0;
    repeat (8) @(negedge clk);

    // --- PART B: 連続ランダムパルス ---
    vld = 1'b1;
    for (int i = 0; i < 300; i++) begin
      @(negedge clk);
      sig = ($urandom_range(0, 2) == 0);
    end
    @(negedge clk);
    vld = 1'b0; sig = 1'b0;
    repeat (LAT + 4) @(negedge clk);

    $display("PART A (procedural)  : n_mismatch = %0d (expected 0)", n_mismatch);
    $display("PART B (assertion)   : n_sva_mid  = %0d (expected 0)", n_sva_mid);
    $display("PART B (assertion)   : n_sva_fail = %0d (expected 0)", n_sva_fail);
    if (n_mismatch == 0 && n_sva_mid == 0 && n_sva_fail == 0)
      $display("*** PASS ***");
    else
      $display("*** FAIL ***");
    $finish;
  end

endmodule
