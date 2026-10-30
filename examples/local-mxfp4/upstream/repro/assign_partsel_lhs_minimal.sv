// -----------------------------------------------------------------------------
// sukimasim Issue #1321 の最小再現 (自己チェック型)
//
//   症状: **連続代入 (`assign`) の左辺が「インデックス付き部分選択」
//         (`vec[base +: W]` / `vec[base -: W]`) のとき、その代入がベクタを
//         一切駆動しない。** ベクタは X のまま動かない。
//
//   引き金はその構文だけ。同じビット範囲でも書き方を変えると通る:
//     - **定数範囲 `assign vec[hi:lo] = x;` は正常** (ケース C。A/B と同じ
//       ビットを同じ順で駆動しているのに結果が違う)。
//     - ビット選択の左辺 `assign vec[i] = x;` は正常。
//     - 同じことを `always_comb` で書けば正常。
//     - ベクタ全体を 1 本の assign で駆動すれば正常。
//     - genvar ループの中か外か、オフセットが定数か genvar かは無関係
//       (A も B も落ちる)。
//
//   期待動作: IEEE 1800-2023 §10.3 は continuous assignment の左辺に
//     「a bit-select, a part-select ... of a vector net or variable」を認めており
//     (Table 10-1 も net / variable の part-select を lvalue として許す)、
//     部分選択の左辺は残りのビットを他の assign が駆動できる点を除いて
//     ビット選択と同じに扱われる。
//     対照の Verilator 5.050 は 5 ケースすべて期待どおり。
//
//   影響: 「配列を packed ベクタへ畳む」ときの最も自然な書き方が黙って壊れる。
//         結果が X になるだけでエラーも警告も出ないため、下流が X を 0 と
//         見なす経路 (2 値化された比較など) では**気付かないまま通る**。
//         本プロジェクトでは UVM の enc env で、観測ポートの配列を
//         インターフェースの packed メンバへ畳む箇所で踏んだ。
//         回避策は always_comb で組み立ててから丸ごと 1 本の assign で渡すこと。
//
//   実行: sukimasim -top tb_assign_partsel_lhs <this file>
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_assign_partsel_lhs;

  localparam int N = 4;
  localparam int W = 3;

  logic [W-1:0] arr [N];

  // A: genvar ループ内の assign。左辺が部分選択
  logic [N*W-1:0] a_gen;
  for (genvar g = 0; g < N; g++) begin : g_a
    assign a_gen[W*g +: W] = arr[g];
  end

  // B: 同じ形を genvar なしで手書き (インデックスは定数)
  logic [N*W-1:0] b_const;
  assign b_const[W*0 +: W] = arr[0];
  assign b_const[W*1 +: W] = arr[1];
  assign b_const[W*2 +: W] = arr[2];
  assign b_const[W*3 +: W] = arr[3];

  // C: 定数の範囲指定 [hi:lo] でも同じか
  logic [N*W-1:0] c_range;
  assign c_range[2:0]   = arr[0];
  assign c_range[5:3]   = arr[1];
  assign c_range[8:6]   = arr[2];
  assign c_range[11:9]  = arr[3];

  // C2: 下向きのインデックス付き部分選択 (-:)
  logic [N*W-1:0] c2_down;
  assign c2_down[W*1-1 -: W] = arr[0];
  assign c2_down[W*2-1 -: W] = arr[1];
  assign c2_down[W*3-1 -: W] = arr[2];
  assign c2_down[W*4-1 -: W] = arr[3];

  // D (対照): always_comb + ループ変数
  logic [N*W-1:0] d_comb;
  always_comb for (int i = 0; i < N; i++) d_comb[W*i +: W] = arr[i];

  // E (対照): 連結でベクタ全体を 1 本の assign で駆動
  logic [N*W-1:0] e_whole;
  assign e_whole = {arr[3], arr[2], arr[1], arr[0]};

  // F (対照): 左辺がビット選択の assign (genvar ループ内)
  logic [N-1:0] f_bit;
  for (genvar g2 = 0; g2 < N; g2++) begin : g_f
    assign f_bit[g2] = arr[g2][0];
  end

  int checks = 0, errors = 0;

  task automatic chk(input string name, input logic [N*W-1:0] got, input logic [N*W-1:0] exp);
    checks++;
    if (got !== exp) begin
      errors++;
      $display("[FAIL] %-50s got=%03h exp=%03h", name, got, exp);
    end else begin
      $display("[ ok ] %-50s = %03h", name, got);
    end
  endtask

  initial begin
    // arr = 1, 2, 3, 4 -> 畳むと 12'b100_011_010_001 = 12'h8D1
    for (int i = 0; i < N; i++) arr[i] = W'(i + 1);
    #1;
    chk("A assign part-select LHS, in a genvar loop",   a_gen,           12'h8D1);
    chk("B assign part-select LHS, constant indices",   b_const,         12'h8D1);
    chk("C assign [hi:lo] LHS, constant range",         c_range,         12'h8D1);
    chk("C2 assign [base -: W] LHS, constant base",     c2_down,        12'h8D1);
    chk("D always_comb + loop variable        [control]", d_comb,        12'h8D1);
    chk("E single whole-vector assign         [control]", e_whole,       12'h8D1);
    // arr[i][0] = 1,0,1,0 -> 4'b0101
    chk("F assign bit-select LHS in a loop    [control]", {8'd0, f_bit}, 12'h005);

    $display("=====================================");
    $display(" assign_partsel_lhs_minimal : %0d checks, %0d errors", checks, errors);
    if (errors == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
