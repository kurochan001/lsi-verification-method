// -----------------------------------------------------------------------------
// sukimasim Issue #1172 の残り (自己チェック型)
//
//   症状: --enable-uvm を付けるだけで、generate for ループの中で
//         **サブモジュールのポートへ繋いだ genvar 依存の選択**
//         (`blk[4*i +: 4]` も `blk[4*i]` も) が反復ごとに評価されなくなる。
//         UVM を一切使っていない設計・TB でも起きる。
//
//   壊れるのはポート接続だけで、同じ generate ブロック内の assign や
//   procedural な for は正しい (このファイルが両方を対照として持っている)。
//
//   #1172 (CLOSED) は「--enable-uvm を付けると演算結果が X になる」だった。
//   X は解消したが、値が黙って壊れる形が残っている。X と違い波形にも
//   警告にも出ないので、こちらの方が危険。
//
//   壊れ方は 2 通り観測している。どちらも同じ原因 (反復ごとの
//   part-select が効かない) だが、下流の見え方が違う。
//     (1) ポートが X になる  … このファイルの via_port
//     (2) 全インスタンスが i=0 のスライスを受け取る … 実環境の MXFP4 BDP。
//         32 個の e2m1_decode がすべて a_block[3:0] を復号し、
//         a2[0..7] = -8 -8 -8 -8 -8 -8 -8 -8 (正しくは -8 1 -8 4 -2 4 0 -4)、
//         sop4 = 32 x 48 = 1536 (正しくは -238) になる。
//         --enable-uvm を外すと同じソースが -238 を返す。
//
//   実行 (対照):
//     sukimasim              -top tb_genvar_partselect <this file>   -> PASS
//     sukimasim --enable-uvm -top tb_genvar_partselect <this file>   -> FAIL
//   対照の Verilator 5.048 は PASS (--enable-uvm に相当するオプションが無い)。
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

// 実環境と同じく「サブモジュールのポートへ part-select を繋ぐ」形
module nib_sink (
  input  logic [3:0] code_i,
  output logic [3:0] code_o
);
  assign code_o = code_i;
endmodule

module bit_sink (
  input  logic bit_i,
  output logic bit_o
);
  assign bit_o = bit_i;
endmodule

module slice_dut (
  input  logic [127:0] blk,
  output logic [3:0]   via_port  [32],   // サブモジュールのポート経由
  output logic [3:0]   via_assign[32],   // generate 内の assign 直接
  output logic         via_bit   [32]    // ポート経由の単純ビット選択 blk[4*i]
);
  for (genvar i = 0; i < 32; i++) begin : g_elem
    nib_sink u_sink (
      .code_i(blk[4*i +: 4]),
      .code_o(via_port[i])
    );
    assign via_assign[i] = blk[4*i +: 4];
    bit_sink u_bsink (
      .bit_i(blk[4*i]),
      .bit_o(via_bit[i])
    );
  end
endmodule

module tb_genvar_partselect;
  logic [127:0] blk;
  logic [3:0]   via_port  [32];
  logic [3:0]   via_assign[32];
  logic         via_bit   [32];

  slice_dut u_dut (.blk(blk), .via_port(via_port), .via_assign(via_assign),
                   .via_bit(via_bit));

  int n_fail_port, n_fail_assign, n_fail_loop, n_fail_bit;
  logic [3:0] via_loop [32];

  // generate を使わず procedural な for で同じことをする対照
  always_comb begin
    for (int i = 0; i < 32; i++) via_loop[i] = blk[4*i +: 4];
  end

  initial begin
    n_fail_port = 0; n_fail_assign = 0; n_fail_loop = 0; n_fail_bit = 0;
    // 要素 i の期待値が i になるパターン
    for (int i = 0; i < 32; i++) blk[4*i +: 4] = 4'(i);
    #1;

    $display("blk = %032h", blk);
    $display("  i : 期待  ポート経由  assign 直接  procedural for");
    for (int i = 0; i < 32; i++) begin
      if (i < 8 || via_port[i] !== 4'(i) || via_assign[i] !== 4'(i) || via_loop[i] !== 4'(i))
        $display("  %2d :  %01h        %01h          %01h            %01h",
                 i, 4'(i), via_port[i], via_assign[i], via_loop[i]);
      if (via_port[i]   !== 4'(i)) n_fail_port++;
      if (via_assign[i] !== 4'(i)) n_fail_assign++;
      if (via_loop[i]   !== 4'(i)) n_fail_loop++;
      if (via_bit[i]    !== i[0])  n_fail_bit++;
    end

    $display("");
    if (n_fail_port != 0)
      $display("[FAIL] generate 内でサブモジュールのポートへ繋いだ part-select が壊れている (%0d/32)",
               n_fail_port);
    else $display("[ ok ] generate + サブモジュールのポート");

    if (n_fail_assign != 0)
      $display("[FAIL] generate 内の assign の part-select が壊れている (%0d/32)",
               n_fail_assign);
    else $display("[ ok ] generate + assign");

    if (n_fail_bit != 0)
      $display("[FAIL] generate 内でポートへ繋いだ単純ビット選択 blk[4*i] も壊れている (%0d/32)",
               n_fail_bit);
    else $display("[ ok ] generate + ポート + 単純ビット選択");

    if (n_fail_loop != 0)
      $display("[FAIL] procedural for の part-select が壊れている (%0d/32)", n_fail_loop);
    else $display("[ ok ] procedural for (対照)");

    $display("=====================================");
    $display(" uvm_mode_genvar_port_select_minimal : %0d failures",
             n_fail_port + n_fail_assign + n_fail_loop + n_fail_bit);
    if (n_fail_port + n_fail_assign + n_fail_loop + n_fail_bit == 0) $display(" *** PASS ***");
    else                                                $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end
endmodule
