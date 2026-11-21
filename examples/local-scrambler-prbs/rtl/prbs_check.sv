// Self-synchronizing PRBS checker for x^N + x^TAP + 1, W received bits per valid clock
// (bit 0 is the earliest). Each received bit is predicted from the N bits received before it,
// so the checker needs no seed and re-aligns by itself N bits after a bit slip.
//   - The first N bits after reset only fill the history and are not checked.
//   - locked rises after LOCK consecutive error-free checked bits.
//   - While locked, each error flag is counted (the counter saturates). LOSS error flags
//     without LOCK error-free bits in a row between them drop the lock.
//   - An all-zero history predicts zero and would call a stuck-at-0 input error free. Such a
//     bit is never counted as error free and drops the lock; stuck reports the condition.
// The bits of one word are processed in order, exactly as W single-bit clocks would.
// MUTATION: 5 counts errors while not locked, 6 accepts the all-zero history,
//           7 never drops the lock on errors, 12 drops the lock one error flag early.
module prbs_check #(parameter N = 7, TAP = 6, W = 1, LOCK = 32, LOSS = 8, CW = 16, MUTATION = 0) (
    input wire clk, rst_n, valid,
    input wire [W-1:0] data,
    output wire [W-1:0] err,
    output reg locked,
    output reg [CW-1:0] count,
    output wire stuck
`ifdef FORMAL
    , output wire [N+$clog2(N+1)+$clog2(LOCK+1)+$clog2(LOSS+1)+CW:0] f_state   // proof only: the state, for the word-boundary invariant
`endif
);
    localparam FW = $clog2(N + 1), GW = $clog2(LOCK + 1), BW = $clog2(LOSS + 1);
    localparam LIMIT = MUTATION == 12 ? LOSS - 1 : LOSS;
    localparam [FW-1:0] FULL = N[FW-1:0];
    localparam [GW-1:0] GOOD = LOCK[GW-1:0];
    localparam [BW-1:0] BAD = LIMIT[BW-1:0];
    reg [N-1:0] hist;
    reg [FW-1:0] fill;
    reg [GW-1:0] good;
    reg [BW-1:0] bad;

    reg [N-1:0] h;
    reg [FW-1:0] f;
    reg [GW-1:0] g;
    reg [BW-1:0] b;
    reg l, e;
    reg [CW-1:0] c;
    reg [W-1:0] flags;
    integer i;
    always @* begin
        h = hist; f = fill; g = good; b = bad; l = locked; c = count;
        flags = {W{1'b0}}; e = 1'b0;
        for (i = 0; i < W; i = i + 1) begin
            if (f != FULL) f = f + 1'b1;
            else begin
                e = data[i] ^ h[N-1] ^ h[TAP-1];
                flags[i] = e;
                if (h == {N{1'b0}} && MUTATION != 6) begin
                    g = 0; b = 0; l = 1'b0;
                end else if (e) begin
                    g = 0;
                    if (l || MUTATION == 5) begin
                        if (c != {CW{1'b1}}) c = c + 1'b1;
                    end
                    if (l) begin
                        b = b + 1'b1;
                        if (b == BAD && MUTATION != 7) begin l = 1'b0; b = 0; end
                        else if (b == BAD) b = 0;
                    end
                end else begin
                    if (g != GOOD) g = g + 1'b1;
                    if (g == GOOD) begin l = 1'b1; b = 0; end
                end
            end
            h = {h[N-2:0], data[i]};
        end
    end
    assign err = valid ? flags : {W{1'b0}};
    assign stuck = fill == FULL && hist == {N{1'b0}};
`ifdef FORMAL
    assign f_state = {hist, fill, good, bad, locked, count};
`endif
    always @(posedge clk) begin
        if (!rst_n) begin
            hist <= {N{1'b0}}; fill <= 0; good <= 0; bad <= 0; locked <= 1'b0; count <= {CW{1'b0}};
        end else if (valid) begin
            hist <= h; fill <= f; good <= g; bad <= b; locked <= l; count <= c;
        end
    end
endmodule
