// Hard-decision Viterbi decoder for the (7,5) rate-1/2 code, four states, register exchange.
//
// Each accepted symbol updates four path metrics and four survivor registers of DEPTH bits.
// The decoded bit is the oldest bit of the survivor of the best state, so the bit of symbol
// n leaves with symbol n + DEPTH - 1. out_valid and out_bit are registered: they are seen
// in the cycle after that symbol. The decoder assumes the encoder starts in state zero.
//
// Rules shared with the reference model:
//   - branch metric: Hamming distance between the received and the expected symbol
//   - on equal metrics the predecessor with u[n-2] = 0 wins
//   - metrics are kept relative to the smallest one; the best state is the lowest index at zero
// The metrics need no saturation: after the subtraction their spread stays below 16
// (the start value is 8), and 5 bits hold it.
//
// DEPTH must be at least 9 (the delay line of mutation 6 needs it).
// MUTATION 2: the larger metric survives.        3: the branch metric ignores c1.
//          4: out_valid starts one symbol early. 5: on equal metrics the other predecessor wins.
//          6: the decision is taken at depth 6 and delayed to the nominal latency.
module viterbi_decoder #(
    parameter DEPTH = 16,
    parameter MUTATION = 0
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       in_valid,
    input  wire [1:0] in_sym,
    output reg        out_valid,
    output reg        out_bit
);
    localparam CW = $clog2(DEPTH + 1);
    localparam integer LAST_I = DEPTH - 1;
    localparam [CW-1:0] LAST = LAST_I[CW-1:0];
    localparam [CW-1:0] ONE = 1;

    reg [4:0] metric [0:3];
    reg [DEPTH-1:0] survivor [0:3];
    reg [CW-1:0] taken;                 // accepted symbols, saturating at DEPTH - 1
    reg [DEPTH-7:0] late;               // used by mutation 6 only

    function [1:0] expected(input [1:0] state, input value);
        expected = {value ^ state[1] ^ state[0], value ^ state[0]};
    endfunction

    function [4:0] distance(input [1:0] difference);
        distance = MUTATION == 3 ? {4'b0000, difference[1]}
                                 : {3'b000, difference[1] & difference[0], difference[1] ^ difference[0]};
    endfunction

    reg [4:0] next_metric [0:3];
    reg [DEPTH-1:0] next_survivor [0:3];
    reg [4:0] m0, m1, low;
    reg [1:0] lower, upper, best;
    reg take_upper;
    integer s;

    always @* begin
        for (s = 0; s < 4; s = s + 1) begin
            lower = {s[0], 1'b0};
            upper = {s[0], 1'b1};
            m0 = metric[lower] + distance(in_sym ^ expected(lower, s[1]));
            m1 = metric[upper] + distance(in_sym ^ expected(upper, s[1]));
            take_upper = MUTATION == 2 ? m1 > m0 : MUTATION == 5 ? m1 <= m0 : m1 < m0;
            next_metric[s] = take_upper ? m1 : m0;
            next_survivor[s] = {take_upper ? survivor[upper][DEPTH-2:0] : survivor[lower][DEPTH-2:0], s[1]};
        end
        low = next_metric[0];
        best = 2'd0;
        for (s = 1; s < 4; s = s + 1)
            if (next_metric[s] < low) begin
                low = next_metric[s];
                best = s[1:0];
            end
    end

    wire ready_now = MUTATION == 4 ? taken + ONE >= LAST : taken == LAST;

    always @(posedge clk) begin
        if (!rst_n) begin
            metric[0] <= 5'd0;
            metric[1] <= 5'd8;
            metric[2] <= 5'd8;
            metric[3] <= 5'd8;
            survivor[0] <= {DEPTH{1'b0}};
            survivor[1] <= {DEPTH{1'b0}};
            survivor[2] <= {DEPTH{1'b0}};
            survivor[3] <= {DEPTH{1'b0}};
            taken <= {CW{1'b0}};
            late <= {(DEPTH-6){1'b0}};
            out_valid <= 1'b0;
            out_bit <= 1'b0;
        end else if (in_valid) begin
            for (s = 0; s < 4; s = s + 1) begin
                metric[s] <= next_metric[s] - low;
                survivor[s] <= next_survivor[s];
            end
            if (taken != LAST) taken <= taken + ONE;
            late <= {late[DEPTH-8:0], next_survivor[best][5]};
            out_valid <= ready_now;
            out_bit <= MUTATION == 6 ? late[DEPTH-7] : next_survivor[best][DEPTH-1];
        end else begin
            out_valid <= 1'b0;
        end
    end
endmodule
