// Self-synchronizing descrambler for x^N + x^TAP + 1, W bits per valid clock (bit 0 is the
// earliest): d[n] = r[n] ^ r[n-TAP] ^ r[n-N]. It has no feedback: N bits after any start,
// slip or error the output depends on received bits alone. One wrong received bit gives
// three wrong data bits, at distances 0, TAP and N.
// MUTATION: 9 wrong tap, 10 history advances without valid.
module ss_descrambler #(parameter N = 58, TAP = 39, W = 1, MUTATION = 0) (
    input wire clk, rst_n, valid,
    input wire [W-1:0] din,
    output wire [W-1:0] dout
`ifdef FORMAL
    , output wire [N-1:0] f_state   // proof only: the state, for the word-boundary invariant
`endif
);
    localparam T = MUTATION == 9 ? TAP - 1 : TAP;
    reg [N-1:0] hist;      // hist[k-1] is the bit received k bits ago
    reg [N+W-1:0] x;       // time order: received bits
    reg [W-1:0] d;
    reg [N-1:0] hist_next;
    integer i;
    always @* begin
        for (i = 0; i < N; i = i + 1) x[i] = hist[N-1-i];
        for (i = 0; i < W; i = i + 1) x[N+i] = din[i];
        for (i = 0; i < W; i = i + 1) d[i] = x[N+i] ^ x[i] ^ x[N+i-T];
        for (i = 1; i <= N; i = i + 1) hist_next[i-1] = x[N+W-i];
    end
    assign dout = d;
`ifdef FORMAL
    assign f_state = hist;
`endif
    always @(posedge clk) begin
        if (!rst_n) hist <= {N{1'b0}};
        else if (valid || MUTATION == 10) hist <= hist_next;
    end
endmodule
