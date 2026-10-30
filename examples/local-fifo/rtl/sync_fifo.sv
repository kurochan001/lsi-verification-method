`timescale 1ns/1ps

// Teaching FIFO: decisions use the occupancy BEFORE the active clock edge.
// No fall-through at empty; no replacement write on a full simultaneous read.
// MUTATION is only for demonstrating checker sensitivity, not production use.
module sync_fifo #(
  parameter integer WIDTH = 8,
  parameter integer DEPTH = 3,
  parameter integer MUTATION = 0,
  parameter integer COUNT_WIDTH = $clog2(DEPTH + 1)
) (
  input wire clk,
  input wire rst_n,
  input wire wr_en,
  input wire rd_en,
  input wire [WIDTH-1:0] wr_data,
  output reg [WIDTH-1:0] rd_data,
  output reg rd_valid,
  output wire full,
  output wire empty,
  output reg [COUNT_WIDTH-1:0] count
);
  localparam integer PTR_WIDTH = DEPTH > 1 ? $clog2(DEPTH) : 1;
  reg [WIDTH-1:0] memory [0:DEPTH-1];
  reg [PTR_WIDTH-1:0] wr_ptr, rd_ptr;
  wire write_accept = wr_en && (!full || MUTATION == 2);
  wire read_accept = rd_en && !empty;

  assign full = count == DEPTH;
  assign empty = count == 0;

  always @(posedge clk) begin
    if (!rst_n) begin
      if (MUTATION != 3 || count === 0 || (^count) === 1'bx) begin
        count <= 0;
        wr_ptr <= 0;
        rd_ptr <= 0;
        rd_data <= 0;
        rd_valid <= 0;
      end
    end else begin
      rd_valid <= read_accept;
      if (write_accept) begin
        memory[wr_ptr] <= wr_data;
        wr_ptr <= wr_ptr == DEPTH - 1 ? 0 : wr_ptr + 1'b1;
      end
      if (read_accept) begin
        rd_data <= MUTATION == 1 ? memory[rd_ptr] ^ {{(WIDTH-1){1'b0}}, 1'b1}
                                : memory[rd_ptr];
        rd_ptr <= rd_ptr == DEPTH - 1 ? 0 : rd_ptr + 1'b1;
      end
      case ({write_accept, read_accept})
        2'b10: count <= count + 1'b1;
        2'b01: count <= count - 1'b1;
        default: count <= count;
      endcase
    end
  end
endmodule
