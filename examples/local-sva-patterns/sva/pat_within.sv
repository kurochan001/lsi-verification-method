// Pattern 3: every req is followed by ack after 1 to N cycles. One ack answers all waiting requests.
`ifndef FORMAL
module pat_within_sva #(parameter N = 3) (
  input logic clk, rst_n, req, ack);
  ap: assert property (@(posedge clk) disable iff (!rst_n) req |-> ##[1:N] ack)
    else $display("PAT_FAIL %m %0t", $time);
  cp: cover property (@(posedge clk) rst_n && req) $display("PAT_HIT %m %0t", $time);
endmodule
`endif

module pat_within_aux #(parameter N = 3) (
  input logic clk, rst_n, req, ack);
  // age[i] is set when a request made i+1 cycles ago has not been answered yet.
  logic [N-1:0] age;
  always @(posedge clk) begin
    if (!rst_n) age <= '0;
    else if (ack) age <= {{(N-1){1'b0}}, req};
    else age <= {age[N-2:0], req};
  end
  wire hit = req;
  wire bad = age[N-1] && !ack;
  `include "pat_report.svh"
endmodule
