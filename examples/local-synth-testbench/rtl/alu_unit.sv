// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// The circuit under test: an ALU with a registered 9-bit result {carry, value}.
// op 0 adds, 1 subtracts (carry = no borrow), 2 is AND and 3 is XOR (carry 0).
module alu_unit #(parameter MUTATION = 0) (
    input wire clk, rst_n,
    input wire [7:0] a, b,
    input wire [1:0] op,
    output reg [8:0] result
);
    wire [8:0] sum = {1'b0, a} + {1'b0, b};
    wire [8:0] diff = {1'b0, a} + {1'b0, ~b} + (MUTATION == 1 ? 9'd0 : 9'd1);
    always @(posedge clk) begin
        if (!rst_n) result <= 9'd0;
        else case (op)
            2'd0: result <= sum;
            2'd1: result <= diff;
            2'd2: result <= {MUTATION == 2 ? sum[8] : 1'b0, MUTATION == 3 ? a ^ b : a & b};
            default: result <= {1'b0, MUTATION == 3 ? a & b : a ^ b};
        endcase
    end
endmodule
