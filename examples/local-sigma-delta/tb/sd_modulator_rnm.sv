`timescale 1ns/1ps
// Real-number model of a 1st- or 2nd-order sigma-delta modulator with a 1-bit quantizer.
//
// The decision y is the sign of the last integrator (+1 when it is exactly zero). On each
// clock the states advance with nonblocking assignments, so a process that samples y on the
// same edge sees the decision of the cycle that is ending.
//
//   order 1: s1 <- s1 + x - y
//   order 2: s1 <- s1 + x - y;  s2 <- s2 + s1 - 2y
//
// The input is a 16-bit code divided by 2**15. With the right coefficients every value is a
// dyadic rational, so the arithmetic is exact and the bit stream equals the Python model.
// MUTATION 1..4 are errors of this model; the testbench maps the others to the CIC.
module sd_modulator_rnm #(parameter ORDER = 2, MUTATION = 0) (
    input  wire               clk,
    input  wire               rst_n,
    input  wire signed [15:0] x_code,
    output wire               y_bit
);
    real s1, s2, x, y;

    initial begin
        s1 = 0.0;
        s2 = 0.0;
    end

    // A continuous assignment is evaluated at time 0, so the first decision is defined even
    // though the states keep their initial value. Mutation 2 decides -1 for a state of exactly 0.
    wire real last = (ORDER == 1) ? s1 : s2;
    assign y_bit = (MUTATION == 2) ? (last > 0.0) : (last >= 0.0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s1 <= 0.0;
            s2 <= 0.0;
        end else begin
            x = $itor(x_code) / 32768.0;
            if (MUTATION == 4) x = x * 0.98;                 // input gain error
            y = y_bit ? 1.0 : -1.0;
            if (ORDER == 1) begin
                if (MUTATION == 1) s1 <= s1 + x - 0.5 * y;   // feedback coefficient error
                else if (MUTATION == 3) s1 <= 0.99 * s1 + x - y;  // leaky integrator
                else s1 <= s1 + x - y;
            end else begin
                if (MUTATION == 3) begin
                    s1 <= 0.99 * s1 + x - y;
                    s2 <= 0.99 * s2 + s1 - 2.0 * y;
                end else begin
                    s1 <= s1 + x - y;
                    s2 <= s2 + s1 - ((MUTATION == 1) ? 1.5 : 2.0) * y;
                end
            end
        end
    end
endmodule
