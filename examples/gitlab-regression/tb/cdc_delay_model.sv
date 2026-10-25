`timescale 1ns/1ps

// Verification-only latency model. Sender holds each value until delivery.
// delay_cycles=1/2/3 means visibility at the first/second/third receiving edge.
// This models digital latency uncertainty, not an analog metastable voltage.
module cdc_delay_model (
  input wire clk,
  input wire rst_n,
  input wire async_value,
  // Explicit net port also works with Icarus 11 in Debian bookworm.
  input wire signed [31:0] delay_cycles,
  output reg value
);
  reg pending = 0;
  reg target = 0;
  integer remaining = 0;

  always @(posedge clk) begin
    if (!rst_n) begin
      value <= 0;
      pending <= 0;
      remaining <= 0;
    end else if (pending) begin
      if (remaining == 1) begin
        value <= target;
        pending <= 0;
      end else begin
        remaining <= remaining - 1;
      end
    end else if (async_value != value) begin
      if (delay_cycles == 1) begin
        value <= async_value;
      end else begin
        target <= async_value;
        remaining <= delay_cycles - 1;
        pending <= 1;
      end
    end
  end
endmodule
