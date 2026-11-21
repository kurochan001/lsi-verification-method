// PRBS generator for x^N + x^TAP + 1, W bits per enabled clock (bit 0 is the earliest).
// hist[k-1] is the bit emitted k bits ago. An all-zero history can never leave zero: the
// generator then emits zeros for ever, which the zero flag reports.
// MUTATION: 1 wrong tap, 2 advances without enable, 3 zero flag stuck low,
//           4 history taken one bit too old when W > 1 (invisible at W = 1).
module prbs_gen #(parameter N = 7, TAP = 6, W = 1, MUTATION = 0) (
    input wire clk, rst_n, enable, seed_load,
    input wire [N-1:0] seed,
    output wire [W-1:0] data,
    output wire zero
`ifdef FORMAL
    , output wire [N-1:0] f_state   // proof only: the state, for the word-boundary invariant
`endif
);
    localparam T = MUTATION == 1 ? TAP - 1 : TAP;
    localparam SKEW = (MUTATION == 4 && W > 1) ? 1 : 0;
    reg [N-1:0] hist;
    reg [N+W-1:0] x;       // time order: x[N-k] = hist[k-1], x[N+i] = new bit i
    reg [N-1:0] hist_next;
    integer i;
    always @* begin
        for (i = 0; i < N; i = i + 1) x[i] = hist[N-1-i];
        for (i = 0; i < W; i = i + 1) x[N+i] = x[i] ^ x[N+i-T];
        for (i = 1; i <= N; i = i + 1) hist_next[i-1] = x[N+W-i-SKEW];
    end
    assign data = x[N+W-1:N];
    assign zero = MUTATION == 3 ? 1'b0 : hist == {N{1'b0}};
`ifdef FORMAL
    assign f_state = hist;
`endif
    always @(posedge clk) begin
        if (!rst_n) hist <= {N{1'b1}};
        else if (seed_load) hist <= seed;
        else if (enable || MUTATION == 2) hist <= hist_next;
    end
endmodule
