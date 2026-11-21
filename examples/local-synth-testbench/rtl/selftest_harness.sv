// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// A synthesizable self-checking test bench: an LFSR drives the ALU, a MISR compresses every
// response and a comparator turns the final signature into one pass bit. It has no delays, no
// file access and no $display, so the same code runs in simulation and on an FPGA.
//
// After start (while idle) the LFSR is loaded with SEED and PATTERNS patterns are applied, one
// per clock. The ALU registers its result, so the response of a pattern enters the signature on
// the next clock. The clock after the last response, done rises and pass holds whether the
// final signature equals GOLDEN. start while busy is ignored; reset clears everything.
module selftest_harness #(
    parameter PATTERNS = 64, SEED = 16'hace1, GOLDEN = 0, MUTATION = 0
) (
    input wire clk, rst_n, start,
    input wire [8:0] fault_xor,          // verification hook for a wrong response; tie to 0
    output reg busy, done, pass,
    output reg [15:0] lfsr,
    output wire [8:0] response,
    output reg [15:0] signature
);
    localparam CW = $clog2(PATTERNS + 1);
    localparam [CW-1:0] LAST = PATTERNS[CW-1:0] - (MUTATION == 6 ? 1 : 0);
    localparam [15:0] SEED_BITS = SEED[15:0];
    localparam [15:0] GOLDEN_BITS = GOLDEN[15:0];
    reg [CW-1:0] issued;
    reg absorb;                          // the response on the ALU output belongs to this run
    wire [8:0] raw;
    alu_unit #(.MUTATION(MUTATION <= 3 ? MUTATION : 0)) dut (
        .clk(clk), .rst_n(rst_n), .a(lfsr[7:0]), .b(lfsr[15:8]), .op({lfsr[12], lfsr[3]}), .result(raw));
    assign response = raw ^ fault_xor;
    wire feedback = lfsr[0] ^ lfsr[2] ^ lfsr[3] ^ (MUTATION == 4 ? lfsr[4] : lfsr[5]);
    wire [8:0] folded_in = MUTATION == 5 ? {1'b0, response[7:0]} : response;
    wire [15:0] next_signature = {signature[14:0], 1'b0} ^ (signature[15] ? 16'h1021 : 16'h0000) ^ {7'd0, folded_in};
    always @(posedge clk) begin
        if (!rst_n) begin
            busy <= 0; done <= 0; pass <= 0; lfsr <= 0; signature <= 0; issued <= 0; absorb <= 0;
        end else if (busy) begin
            if (issued != LAST) begin
                lfsr <= {feedback, lfsr[15:1]};
                issued <= issued + 1'b1;
            end
            absorb <= issued != LAST;
            if (absorb) signature <= next_signature;
            if (absorb && issued == LAST) begin
                busy <= 0;
                done <= 1;
                pass <= (MUTATION == 7 ? signature : next_signature) == GOLDEN_BITS;
            end
        end else if (start) begin
            busy <= 1; done <= 0; pass <= 0; lfsr <= SEED_BITS; signature <= 0; issued <= 0; absorb <= 0;
        end
    end
endmodule
