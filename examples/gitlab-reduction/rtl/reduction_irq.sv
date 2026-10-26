`timescale 1ns/1ps
module reduction_irq #(
  parameter integer MUTATION = 0
) (
  input wire clk, rst_n, event_accept, clear_accept, irq_en,
  output wire pend, irq
);
  integer event_streak;
  // Additional evaluation defect: long event bursts wrongly suppress storage.
  wire delivered_event = event_accept && !(MUTATION == 4 && event_streak >= 8);
  irq_pending #(.MUTATION(MUTATION == 4 ? 0 : MUTATION)) core (
    clk, rst_n, delivered_event, clear_accept, irq_en, pend, irq
  );
  always @(posedge clk) begin
    if (!rst_n || !event_accept) event_streak <= 0;
    else event_streak <= event_streak + 1;
  end
endmodule
