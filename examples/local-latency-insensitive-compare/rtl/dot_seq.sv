// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Sequential 4-lane dot product: one multiply-accumulate per clock and one
// transaction in flight. A result is held until it is taken.
module dot_seq #(
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
    reg [63:0] op;
    reg [1:0] step;
    reg busy, done;
    reg signed [17:0] acc;

    wire pop = done && out_ready;
    assign in_ready = rst_n && !busy && (!done || out_ready);
    assign out_valid = rst_n && done;
    assign out_data = acc;
    wire accept = in_valid && in_ready;

    wire signed [7:0] ea = op[8*step +: 8];
    wire signed [7:0] eb = op[32 + 8*step +: 8];
    wire signed [15:0] prod = ea * eb;
    wire signed [17:0] prod18 = {{2{prod[15]}}, prod};

    always @(posedge clk) begin
        if (!rst_n) begin
            op <= 64'd0;
            step <= 2'd0;
            busy <= 1'b0;
            done <= 1'b0;
            acc <= 18'sd0;
        end else begin
            if (pop) done <= 1'b0;
            // Mutation 8: a new request accepted in the same cycle as a delivery is lost.
            if (accept && !(MUTATION == 8 && pop)) begin
                op <= in_data;
                step <= 2'd0;
                busy <= 1'b1;
                // Mutation 9: the accumulator keeps the previous result.
                if (MUTATION != 9) acc <= 18'sd0;
            end else if (busy) begin
                acc <= acc + prod18;
                step <= step + 2'd1;
                if (step == 2'd3) begin
                    busy <= 1'b0;
                    done <= 1'b1;
                end
            end
        end
    end
endmodule
