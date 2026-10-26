`timescale 1ns/1ps
// A synchronous, buffered ready/valid stream. No empty bypass.
module stream_buffer #(
  parameter integer WIDTH = 8,
  parameter integer DEPTH = 3,
  parameter integer MUTATION = 0
) (
  input wire clk, rst_n,
  input wire s_valid,
  output wire s_ready,
  input wire [WIDTH-1:0] s_data,
  output wire m_valid,
  input wire m_ready,
  output wire [WIDTH-1:0] m_data
);
  localparam integer PTR_WIDTH = DEPTH > 1 ? $clog2(DEPTH) : 1;
  reg [WIDTH-1:0] memory [0:DEPTH-1];
  reg [PTR_WIDTH-1:0] wr_ptr, rd_ptr;
  integer count;
  wire push = s_valid && s_ready;
  wire pop = m_valid && m_ready;
  // Defect 3: a consumed item remains available when there is no replacement.
  wire release_item = pop && !(MUTATION == 3 && !push);
  assign m_valid = count > 0;
  assign m_data = memory[rd_ptr];
  assign s_ready = count < DEPTH || pop;
  always @(posedge clk) begin
    if (!rst_n) begin
      count <= 0; wr_ptr <= 0; rd_ptr <= 0;
    end else begin
      if (push) begin
        // Defect 2: lose the incoming item on a full-buffer replacement.
        if (!(MUTATION == 2 && count == DEPTH && pop)) memory[wr_ptr] <= s_data;
        wr_ptr <= wr_ptr == DEPTH - 1 ? 0 : wr_ptr + 1'b1;
      end
      if (release_item) rd_ptr <= rd_ptr == DEPTH - 1 ? 0 : rd_ptr + 1'b1;
      case ({push, release_item})
        2'b10: count <= count + 1;
        2'b01: count <= count - 1;
        default: count <= count;
      endcase
      // Defect 1: overwrite a presented item while the receiver is stalled.
      if (MUTATION == 1 && m_valid && !m_ready && s_valid) memory[rd_ptr] <= s_data;
    end
  end
endmodule
