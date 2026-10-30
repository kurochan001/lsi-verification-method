`timescale 1ns/1ps

// -----------------------------------------------------------------------------
// hw_clkgen
//   UVM トップ共通のクロック生成。hw_top / hw_enc_top から使う。
//
//   sukimasim 0.9.9.2 では run_test() を呼ぶモジュール自身に属する静的プロセス
//   (initial / always / そこから fork した子) が、run phase の objection が
//   0 になった瞬間にすべて kill される (Issue #1176)。トップに
//   initial forever #5 clk = ~clk; を置くと drain time 中にクロックが止まり、
//   パイプラインが吐き出せずに out_valid が一度も立たない。
//   サブモジュールに属するプロセスは kill されないので、ここへ追い出す。
// -----------------------------------------------------------------------------
module hw_clkgen #(parameter time HALF = 5ns) (output logic clk);
  initial begin
    clk = 1'b0;
    forever #HALF clk = ~clk;
  end
endmodule
