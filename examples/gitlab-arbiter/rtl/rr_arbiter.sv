`timescale 1ns/1ps
module rr_arbiter #(
  parameter integer PORTS = 3,
  parameter integer MUTATION = 0
) (
  input wire clk, rst_n,
  input wire [PORTS-1:0] req,
  input wire ready,
  output reg [PORTS-1:0] grant
);
  integer cursor, locked_port;
  integer selected, candidate;
  reg locked, found;
  always @* begin
    grant = 0; selected = 0; found = 0; candidate = 0;
    if (locked && MUTATION != 2) begin
      selected = locked_port; grant[locked_port] = 1; found = 1;
    end else begin
      for (integer offset = 0; offset < PORTS; offset = offset + 1) begin
        candidate = (cursor + offset) % PORTS;
        if (!found && req[candidate]) begin
          grant[candidate] = 1; selected = candidate; found = 1;
        end
      end
    end
    // Defect 1: grant every requester, violating mutual exclusion.
    if (MUTATION == 1) grant = req;
  end
  always @(posedge clk) begin
    if (!rst_n) begin cursor <= 0; locked <= 0; locked_port <= 0; end
    else if (found) begin
      if (ready) begin
        locked <= 0;
        // Defect 3: fixed priority instead of rotating after acceptance.
        cursor <= MUTATION == 3 ? 0 : (selected + 1) % PORTS;
      end else begin
        locked <= 1; locked_port <= selected;
      end
    end
  end
endmodule
