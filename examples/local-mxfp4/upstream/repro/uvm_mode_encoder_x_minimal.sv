// -----------------------------------------------------------------------------
// --enable-uvm を付けるだけで RTL の出力が X になる — 再現ケース
//
//   対象: sukimasim 0.9.9.2 (Issue #1172)
//   規格: --enable-uvm は UVM ライブラリを有効化するオプションであり、
//         UVM を使っていない設計・テストベンチの評価結果を変えてはならない。
//
//   観測される症状 (sukimasim 0.9.9.2):
//     UVM を一切参照していない下の TB を、同じソース・同じ入力で
//     オプションだけ変えて実行すると結果が変わる。
//       sukimasim              -> blk_o = 8164216421642164216421642164216421
//       sukimasim --enable-uvm -> blk_o = 817XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
//     上位 8bit (共有スケール) は保持され、下位 128bit (要素) が X になる。
//     -assert や +define+... の有無は無関係で、--enable-uvm だけが効く。
//
//   より大きい再現 (プレーン SV の回帰そのもの):
//       make sim-sukima N_SERIES=10 N_ENC=3           -> 7 checks, 0 errors
//       上と同じファイルに --enable-uvm を足すだけ    -> 7 checks, 3 errors
//
//   実務上の影響:
//     UVM ベースの検証環境では DUT が X を返すため、スコアボードが全件不一致に
//     なる。TB 側を疑って延々と切り分けることになる (本プロジェクトでは付録A の
//     UVM env 立ち上げでこれを踏み、env のコードが完成しても検証を進められない)。
//
//   回避策:
//     現状なし (--enable-uvm を外すと UVM マクロが解決できない)。
//
//   実行 (行頭に "verilator" を置くと BADVLTPRAGMA になるため $ で始める):
//     $ sukimasim -top tb_enc_uvm_mode \
//         rtl/mxfp4_pkg.sv rtl/e2m1_quantize.sv rtl/amax_tree32.sv \
//         rtl/quant_encoder.sv repro/uvm_mode_encoder_x_minimal.sv
//     $ sukimasim --enable-uvm -top tb_enc_uvm_mode <同じファイル群>
//
//   期待値: どちらのモードでも n_fail = 0 (通常モードはそうなる)
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

module tb_enc_uvm_mode;
  import mxfp4_pkg::*;

  logic clk, rst_n;
  initial begin
    clk = 1'b0;
    forever #5 clk = ~clk;
  end

  logic               in_valid;
  logic [31:0]        v [K];
  logic [BLOCK_W-1:0] blk_o;
  logic               out_valid;

  quant_encoder u_enc (
    .clk            (clk),
    .rst_n          (rst_n),
    .in_valid       (in_valid),
    .v_i            (v),
    .blk_o          (blk_o),
    .out_valid      (out_valid),
    .e_rel_dbg      (),
    .mag3_dbg       (),
    .tie_hit_dbg    (),
    .quant_valid_dbg()
  );

  // 通常モードで得られる値。要素は 32 レーンすべてが同じ 4 パターンの繰り返し。
  localparam logic [BLOCK_W-1:0] EXP_BLK = 136'h8164216421642164216421642164216421;

  int n_fail = 0;

  initial begin
    rst_n    = 1'b1;
    in_valid = 1'b0;
    for (int i = 0; i < K; i++) v[i] = 32'h0;
    #1 rst_n = 1'b0;
    repeat (3) @(negedge clk);
    rst_n = 1'b1;

    // 固定パターン (指数 0x80..0x83、仮数は i*7)
    @(negedge clk);
    for (int i = 0; i < K; i++) v[i] = {1'b0, 8'(8'h80 + (i % 4)), 23'(i * 7)};
    in_valid = 1'b1;
    @(negedge clk);
    in_valid = 1'b0;
    repeat (ENC_LAT) @(negedge clk);

    $display("blk_o = %034h", blk_o);
    if (^blk_o === 1'bx) begin
      n_fail++;
      $display("[FAIL] blk_o contains X");
    end
    if (blk_o !== EXP_BLK) begin
      n_fail++;
      $display("[FAIL] blk_o mismatch: exp=%034h", EXP_BLK);
    end

    $display("=====================================");
    $display(" uvm_mode_encoder_x_minimal : %0d failures", n_fail);
    if (n_fail == 0) $display(" *** PASS ***");
    else             $display(" *** FAIL ***");
    $display("=====================================");
    $finish;
  end

endmodule
