// Self-synchronizing (multiplicative) scrambler for x^N + x^TAP + 1, W bits per valid clock
// (bit 0 is the earliest): s[n] = d[n] ^ s[n-TAP] ^ s[n-N]. hist[k-1] is the scrambled bit
// sent k bits ago. Reset fills the history with ones, so zero data does not start as zeros.
// MUTATION: 8 history takes the data instead of the scrambled bit,
//           11 history taken one bit too old when W > 1 (invisible at W = 1).
module ss_scrambler #(parameter N = 58, TAP = 39, W = 1, MUTATION = 0) (
    input wire clk, rst_n, valid,
    input wire [W-1:0] din,
    output wire [W-1:0] dout
`ifdef FORMAL
    , output wire [N-1:0] f_state   // proof only: the state, for the word-boundary invariant
`endif
);
    localparam SKEW = (MUTATION == 11 && W > 1) ? 1 : 0;
    reg [N-1:0] hist;
    reg [N+W-1:0] x, y;    // time order; x: scrambled bits, y: what the history will hold
    reg [N-1:0] hist_next;
    integer i;
    always @* begin
        for (i = 0; i < N; i = i + 1) begin x[i] = hist[N-1-i]; y[i] = hist[N-1-i]; end
        for (i = 0; i < W; i = i + 1) begin
            x[N+i] = din[i] ^ y[i] ^ y[N+i-TAP];
            y[N+i] = MUTATION == 8 ? din[i] : x[N+i];
        end
        for (i = 1; i <= N; i = i + 1) hist_next[i-1] = y[N+W-i-SKEW];
    end
    assign dout = x[N+W-1:N];
`ifdef FORMAL
    assign f_state = hist;
`endif
    always @(posedge clk) begin
        if (!rst_n) hist <= {N{1'b1}};
        else if (valid) hist <= hist_next;
    end
endmodule
