// Formal top for the two-clock design. Both clocks are derived from the solver's global
// clock and may each pause for any number of steps, so every frequency ratio and phase is
// covered. Reset is held while both clocks run for the first four steps.
module cross_formal #(parameter MUTATION = 0) (
  input logic evt,
  input logic run_a,
  input logic run_b
);
  (* gclk *) reg step_clk;
  logic       clk = 1'b0, clk_b = 1'b0;
  logic [2:0] steps = 3'd0;
  wire        started = steps == 3'd4;
  logic       evt_ready, note_b;
  always @(posedge step_clk) begin
    if (!started) steps <= steps + 3'd1;
    if (!started || run_a) clk <= !clk;
    if (!started || run_b) clk_b <= !clk_b;
  end
  event_cross #(.MUTATION(MUTATION)) u_cross (
    .clk(clk), .rst_n(started), .evt(evt), .evt_ready(evt_ready), .clk_b(clk_b),
    .rst_b_n(started), .note_b(note_b));
endmodule
