`timescale 1ns/1ps

// Fictional specification: a simultaneous event wins over a W1C clear.
// MUTATION is a verification-only selection; production RTL would omit it.
module irq_pending #(
  parameter integer MUTATION = 0
) (
  input wire clk,
  input wire rst_n,
  input wire event_accept,
  input wire clear_accept,
  input wire irq_en,
  output reg pend,
  output wire irq
);
  assign irq = pend && irq_en;

  always @(posedge clk) begin
    if (!rst_n)
      pend <= 1'b0;
    else if (MUTATION == 1 && clear_accept)
      pend <= 1'b0;  // Deliberate error: clear wins over an event.
    else if (event_accept && (MUTATION != 2 || irq_en))
      pend <= 1'b1;  // MUTATION=2 incorrectly masks event storage.
    else if (clear_accept)
      pend <= 1'b0;
  end
endmodule
