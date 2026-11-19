// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Multiply two 6-bit operands and optionally double the product. The product takes more than one
// clock period, so the result register loads two edges after the operands (a multicycle path).
//   edge 0: start accepted, operands and cfg loaded      edge 2: result loaded
//   edge 1: wait                                         edge 3: done for one cycle
// MUTATION 1 loads the result at edge 1. MUTATION 3 clocks `done` through a delay cell.
// MUTATION 2 is not in the RTL: it is a late cfg input and a constraint that hides it.
module mc_scale #(parameter MUTATION = 0) (
    input  wire        clk, rst_n, start, cfg,
    input  wire [5:0]  a, b,
    output reg         busy, done,
    output reg  [12:0] result
);
    reg [5:0] a_q, b_q;
    reg cfg_q, phase, fire;
    wire [11:0] product = a_q * b_q;
    wire load = !busy && start;
    wire capture = busy && (phase || MUTATION == 1);
    wire clk_done;
    generate if (MUTATION == 3) begin : g_skew
        CKDLY skew(.A(clk), .Y(clk_done));
    end else begin : g_same
        assign clk_done = clk;
    end endgenerate
    // Control is reset; the data registers are not, and hold X until their first load.
    always @(posedge clk) begin
        if (!rst_n) begin
            busy <= 1'b0; phase <= 1'b0; fire <= 1'b0;
        end else begin
            fire <= capture;
            if (load) begin busy <= 1'b1; phase <= 1'b0; end
            else if (capture) busy <= 1'b0;
            else if (busy) phase <= 1'b1;
        end
    end
    always @(posedge clk) begin
        if (load) begin a_q <= a; b_q <= b; cfg_q <= cfg; end
        if (capture) result <= cfg_q ? {product, 1'b0} : {1'b0, product};
    end
    // No logic between fire and done: with the late clock of MUTATION 3, fire changes just after it.
    always @(posedge clk_done) done <= fire;
endmodule
