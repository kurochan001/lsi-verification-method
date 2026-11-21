// Pattern 6: an event accepted at clk is followed by note at clk_b within N edges of clk_b.
// A clk_b edge that coincides with the accepting clk edge is not counted. N is 2 or more.
// A second event before the first note is also reported.
// Neither tool accepts a multiclocked property, so only the helper-register form exists.
module pat_cross_aux #(parameter N = 3) (
  input logic clk, rst_n, accept, input logic clk_b, rst_b_n, note);
  logic       sent, seen, pending;
  logic [3:0] edges;
  always @(posedge clk) begin
    if (!rst_n) sent <= 1'b0;
    else if (accept) sent <= !sent;
  end
  wire fresh = sent != seen;
  always @(posedge clk_b) begin
    if (!rst_b_n) begin
      seen <= 1'b0;
      pending <= 1'b0;
      edges <= 4'd0;
    end else if (fresh) begin
      seen <= sent;
      pending <= 1'b1;
      edges <= 4'd1;
    end else if (pending) begin
      if (note) pending <= 1'b0;
      edges <= edges + 4'd1;
    end
  end
  wire hit_b = fresh;
  wire bad_b = pending && !note && (fresh || edges == N - 1);
`ifdef FORMAL
  always @(posedge clk_b) if (rst_b_n) begin
    a_pattern: assert (!bad_b);
    c_antecedent: cover (hit_b);
  end
`else
  always @(posedge clk_b) if (rst_b_n) begin
    if (bad_b) $display("PAT_FAIL %m %0t", $time);
    if (hit_b) $display("PAT_HIT %m %0t", $time);
  end
`endif
endmodule
