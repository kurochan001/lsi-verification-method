// Pattern 5b: items leave in the order they entered, with the same contents.
// One item is followed at a time: its payload and the number of items ahead of it are kept.
`ifndef FORMAL
// Assertion form with property local variables and an unbounded repetition. It is legal
// SystemVerilog, but Verilator 5.052 does not evaluate it correctly, so it is used only as a
// recorded tool difference and is never bound to the design.
module pat_order_sva #(parameter W = 8, parameter CW = 4) (
  input logic clk, rst_n, push, pop, input logic [W-1:0] din, dout);
  logic [CW-1:0] occ;
  always @(posedge clk) begin
    if (!rst_n) occ <= '0;
    else occ <= occ + {{(CW-1){1'b0}}, push} - {{(CW-1){1'b0}}, pop};
  end
  wire [CW-1:0] ahead = occ - {{(CW-1){1'b0}}, pop};
  property p_order;
    logic [W-1:0] x;
    logic [CW-1:0] k;
    @(posedge clk) disable iff (!rst_n)
      (push, x = din, k = ahead)
      ##1 (!(pop && k == 0), k = k - {{(CW-1){1'b0}}, pop})[*0:$]
      ##1 (pop && k == 0) |-> dout == x;
  endproperty
  ap: assert property (p_order) else $display("PAT_FAIL %m %0t", $time);
  cp: cover property (@(posedge clk) rst_n && push) $display("PAT_HIT %m %0t", $time);
endmodule
`endif

module pat_order_aux #(parameter W = 8, parameter CW = 4, parameter FREE_PICK = 0) (
  input logic clk, rst_n, push, pop, input logic [W-1:0] din, dout);
  logic [CW-1:0] occ, ahead;
  logic          tracking;
  logic [W-1:0]  kept;
`ifdef FORMAL
  // The solver chooses which item to follow, so every item is covered.
  wire pick_any = $anyseq;
  wire pick = FREE_PICK != 0 ? pick_any : 1'b1;
`else
  wire pick = 1'b1;
`endif
  wire capture = push && !tracking && pick;
  wire leave   = tracking && pop && ahead == '0;
  always @(posedge clk) begin
    if (!rst_n) begin
      occ <= '0;
      tracking <= 1'b0;
    end else begin
      occ <= occ + {{(CW-1){1'b0}}, push} - {{(CW-1){1'b0}}, pop};
      if (capture) begin
        tracking <= 1'b1;
        kept <= din;
        ahead <= occ - {{(CW-1){1'b0}}, pop};
      end else if (leave) tracking <= 1'b0;
      else if (tracking && pop) ahead <= ahead - 1'b1;
    end
  end
  wire hit = capture;
  wire bad = leave && dout != kept;
  `include "pat_report.svh"
endmodule
