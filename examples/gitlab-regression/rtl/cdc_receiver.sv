`timescale 1ns/1ps

// Two synchronized copies of a toggle may arrive on different cycles.
// Accept only after agreement, and accept each stable toggle exactly once.
module cdc_receiver #(
  parameter integer EARLY_A_ONLY = 0
) (
  input wire clk,
  input wire rst_n,
  input wire a,
  input wire b,
  output reg accepted_toggle,
  output reg pulse
);
  always @(posedge clk) begin
    if (!rst_n) begin
      accepted_toggle <= 0;
      pulse <= 0;
    end else begin
      pulse <= 0;
      if ((EARLY_A_ONLY || a == b) && a != accepted_toggle) begin
        accepted_toggle <= a;
        pulse <= 1;
      end
    end
  end
endmodule
