// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Common top for both implementations so the same harness drives either one.
// IMPL=0 selects the sequential version, IMPL=1 the pipelined version.
module li_dut #(
    parameter integer IMPL = 0,
    parameter integer SPLIT = 0,
    parameter integer MUTATION = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [63:0] in_data,
    output wire        out_valid,
    input  wire        out_ready,
    output wire [17:0] out_data
);
    generate
        if (IMPL != 0) begin : g_pipe
            dot_pipe #(.SPLIT(SPLIT), .MUTATION(MUTATION)) u_impl (
                .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready), .in_data(in_data),
                .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data));
        end else begin : g_seq
            dot_seq #(.MUTATION(MUTATION)) u_impl (
                .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready), .in_data(in_data),
                .out_valid(out_valid), .out_ready(out_ready), .out_data(out_data));
        end
    endgenerate
endmodule
