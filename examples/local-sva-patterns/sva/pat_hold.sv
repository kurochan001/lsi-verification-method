// Pattern 1: while valid waits for ready, valid stays high and the payload does not change.
`ifndef FORMAL
module pat_hold_sva #(parameter W = 8) (
  input logic clk, rst_n, valid, ready, input logic [W-1:0] data);
  ap: assert property (@(posedge clk) disable iff (!rst_n)
    valid && !ready |=> valid && $stable(data))
    else $display("PAT_FAIL %m %0t", $time);
  cp: cover property (@(posedge clk) rst_n && valid && !ready) $display("PAT_HIT %m %0t", $time);
endmodule
`endif

module pat_hold_aux #(parameter W = 8) (
  input logic clk, rst_n, valid, ready, input logic [W-1:0] data);
  logic         waiting;
  logic [W-1:0] held;
  always @(posedge clk) begin
    if (!rst_n) waiting <= 1'b0;
    else begin
      waiting <= valid && !ready;
      held <= data;
    end
  end
  wire hit = valid && !ready;
  wire bad = waiting && !(valid && data == held);
  `include "pat_report.svh"
endmodule
