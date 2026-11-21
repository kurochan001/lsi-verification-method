// Pattern 2: while en is high, exactly one bit of vec is set.
`ifndef FORMAL
module pat_onehot_sva #(parameter W = 4) (
  input logic clk, rst_n, en, input logic [W-1:0] vec);
  ap: assert property (@(posedge clk) disable iff (!rst_n) en |-> $onehot(vec))
    else $display("PAT_FAIL %m %0t", $time);
  cp: cover property (@(posedge clk) rst_n && en) $display("PAT_HIT %m %0t", $time);
endmodule
`endif

module pat_onehot_aux #(parameter W = 4) (
  input logic clk, rst_n, en, input logic [W-1:0] vec);
  // Written without $onehot so that the form does not depend on one system function.
  wire hit = en;
  wire bad = en && (vec == '0 || (vec & (vec - 1'b1)) != '0);
  `include "pat_report.svh"
endmodule
