// Shared reporting for the helper-register forms. Each module provides clk, rst_n, bad and hit.
// With FORMAL the same two signals become an assertion and a cover; in simulation they are logged.
`ifdef FORMAL
  always @(posedge clk) if (rst_n) begin
    a_pattern: assert (!bad);
    c_antecedent: cover (hit);
  end
`else
  always @(posedge clk) if (rst_n) begin
    if (bad) $display("PAT_FAIL %m %0t", $time);
    if (hit) $display("PAT_HIT %m %0t", $time);
  end
`endif
