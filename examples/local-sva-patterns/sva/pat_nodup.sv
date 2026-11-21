// Pattern 4: an identifier is not started again before its own completion has passed.
// A start in the same cycle as the completion still counts as a duplicate.
`ifndef FORMAL
module pat_nodup_sva #(parameter IDS = 4, parameter IW = 2) (
  input logic clk, rst_n, start, done, input logic [IW-1:0] tag, dtag);
  // One property per identifier replaces a property local variable, which Verilator 5.052
  // rejects when it crosses a sequence operator. "until_with" is used instead of
  // "throughout ... [->1]": Verilator 5.052 misses the completion when it comes in the first
  // cycle after the start, and then reports a later legal start (see probes/).
  for (genvar i = 0; i < IDS; i++) begin : g_id
    ap: assert property (@(posedge clk) disable iff (!rst_n)
      (start && tag == i) |=> (!(start && tag == i)) until_with (done && dtag == i))
      else $display("PAT_FAIL %m %0t", $time);
  end
  cp: cover property (@(posedge clk) rst_n && start) $display("PAT_HIT %m %0t", $time);
endmodule
`endif

module pat_nodup_aux #(parameter IDS = 4, parameter IW = 2) (
  input logic clk, rst_n, start, done, input logic [IW-1:0] tag, dtag);
  logic [IDS-1:0] open;
  always @(posedge clk) begin
    if (!rst_n) open <= '0;
    else begin
      if (done) open[dtag] <= 1'b0;
      if (start) open[tag] <= 1'b1;
    end
  end
  wire hit = start;
  wire bad = start && open[tag];
  `include "pat_report.svh"
endmodule
