// Proof harness for the token bucket.
//
// The window bound. A free input f_start picks the first cycle of a window: the window begins at
// the first cycle out of reset where f_start is 1 and lasts until the next reset. Because f_start
// is free, every start time and every length is covered by one proof. For the window starting at
// cycle s and the grants G counted up to cycle e, the specification is
//     cost * G  <=  cap(s) + rate(s+1) + ... + rate(e)
// The harness keeps the difference D = right side - left side, capped at the largest bucket. The
// cap only lowers D (D only grows by additions after it), so the capped value never exceeds the
// true one, and "capped D >= 0" implies the bound. Capping keeps the state finite, so induction
// can close. f_len counts the length of the window, saturating, for the cover goals.
//
// CHECKS selects the assertions:
//   0 all: the window bound, its lemma, and the step checks against a reference written here
//   1 the window bound and its lemma only (enough for the induction proof)
//   2 the window bound only (a bounded check needs no lemma)
module rate_limiter_formal #(parameter FRAC = 2, DEPTH_W = 2, RATE_W = 3, MUTATION = 0, CHECKS = 0) (
    input wire clk, rst_n, req, f_start,
    input wire [DEPTH_W-1:0] depth,
    input wire [RATE_W-1:0] rate
);
    localparam TW = DEPTH_W + FRAC;
    localparam WW = (TW > RATE_W ? TW : RATE_W) + 3;     // wide enough for every sum below
    localparam [WW-1:0] ONE = 1;
    localparam [WW-1:0] COST = ONE << FRAC;
    localparam [WW-1:0] CAP_MAX = ((ONE << DEPTH_W) - ONE) << FRAC;
    localparam [WW-1:0] CARRY = ONE << TW;

    wire grant;
    wire [TW-1:0] tokens;
    token_bucket #(.FRAC(FRAC), .DEPTH_W(DEPTH_W), .RATE_W(RATE_W), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .depth(depth), .rate(rate), .req(req), .grant(grant), .tokens(tokens));

    // Reference arithmetic on the design's own level, in a width that cannot overflow.
    wire [WW-1:0] r_cap = {{(WW-DEPTH_W){1'b0}}, depth} << FRAC;
    wire [WW-1:0] r_level = {{(WW-TW){1'b0}}, tokens};
    wire [WW-1:0] r_sum = r_level + {{(WW-RATE_W){1'b0}}, rate};
    wire [WW-1:0] r_avail = r_sum < r_cap ? r_sum : r_cap;
    wire          r_grant = req && r_avail >= COST;
    wire [WW-1:0] r_next = r_avail - (r_grant ? COST : {WW{1'b0}});
    wire [WW-1:0] spent = grant ? COST : {WW{1'b0}};
    wire [WW-1:0] refill = {{(WW-RATE_W){1'b0}}, rate};

    reg f_past = 0, f_active = 0;
    reg signed [WW:0] f_slack = 0;
    reg [2:0] f_len = 0;
    reg [WW-1:0] f_next = 0, f_cap = 0;
    wire signed [WW:0] grown = f_slack + $signed({1'b0, refill}) - $signed({1'b0, spent});
    wire signed [WW:0] cap_max = $signed({1'b0, CAP_MAX});
    always @(posedge clk) begin
        f_past <= 1;
        f_next <= r_next;
        f_cap <= r_cap;
        if (!rst_n) begin
            f_active <= 0;
            f_len <= 0;
        end else if (!f_active) begin
            if (f_start) begin
                f_active <= 1;
                f_len <= 1;
                f_slack <= $signed({1'b0, r_cap}) - $signed({1'b0, spent});
            end
        end else begin
            f_len <= f_len == 3'd7 ? f_len : f_len + 3'd1;
            f_slack <= grown > cap_max ? cap_max : grown;
        end
    end

    always @(posedge clk) begin
        if (!f_past) as_initial_reset: assume(!rst_n);
        if (f_past && f_active) ap_window: assert(f_slack >= 0);
    end

    generate
        if (CHECKS != 2) begin : g_lemma
            // The level never exceeds what the window has left: the induction invariant.
            always @(posedge clk)
                if (f_past && f_active) ai_slack: assert(f_slack >= $signed({{(WW-TW+1){1'b0}}, tokens}));
        end
        if (CHECKS == 0) begin : g_steps
            always @(posedge clk) begin
                if (f_past) begin
                    ap_grant: assert(grant == r_grant);
                    if ($past(rst_n)) ap_level: assert({{(WW-TW){1'b0}}, tokens} == f_next);
                    else ap_reset: assert({{(WW-TW){1'b0}}, tokens} == f_cap);
                    cp_burst: cover(f_active && f_len == 3'd4 && f_slack == 0 && $past(grant, 3) && $past(grant, 2) && $past(grant) && grant);
                    cp_carry: cover(rst_n && r_sum >= CARRY && r_grant);
                    cp_short: cover(rst_n && req && r_avail == COST - ONE);
                    cp_clamp: cover(rst_n && $past(rst_n) && r_cap < $past(r_cap) && r_level > r_cap);
                    cp_zero_rate: cover(f_active && f_len == 3'd3 && rate == 0 && $past(rate) == 0 && grant);
                end
            end
        end
    endgenerate
endmodule
