// Iterative signed/unsigned divider with the RISC-V M-extension results for the special
// cases. Division by zero, signed overflow and |dividend| < |divisor| finish in one cycle;
// every other division runs W restoring steps on the magnitudes and fixes the signs last.
module divider #(parameter W = 32, MUTATION = 0) (
    input  wire         clk, rst_n, flush,
    input  wire         in_valid, in_signed,
    input  wire [W-1:0] in_dividend, in_divisor,
    output wire         in_ready,
    output reg          out_valid,
    input  wire         out_ready,
    output reg  [W-1:0] out_quotient, out_remainder);
    localparam CW = $clog2(W);
    localparam [W-1:0] MIN = {1'b1, {W-1{1'b0}}};
    localparam integer STEPS = W - 1;
    localparam [CW-1:0] LAST = STEPS[CW-1:0];
    reg busy, neg_q, neg_r;
    reg [CW-1:0] count;
    reg [W-1:0] divisor, quo, rem;
    assign in_ready = rst_n && !busy && !out_valid && !flush;

    wire a_neg = in_signed && in_dividend[W-1];
    wire b_neg = in_signed && in_divisor[W-1];
    wire [W-1:0] a_mag = a_neg ? -in_dividend : in_dividend;
    wire [W-1:0] b_mag = b_neg ? -in_divisor : in_divisor;
    wire zero = in_divisor == 0;
    wire overflow = in_signed && in_dividend == MIN && &in_divisor;
    // Mutation 3 also takes the shortcut when the magnitudes are equal.
    wire lesser = MUTATION == 3 ? a_mag <= b_mag : a_mag < b_mag;

    // One restoring step: shift the next dividend bit into the partial remainder.
    wire [W:0] trial = {rem, quo[W-1]};
    wire fits = trial >= {1'b0, divisor};
    wire [W-1:0] reduced = trial[W-1:0] - divisor;  // below the divisor whenever it fits
    wire [W-1:0] rem_next = fits ? reduced : trial[W-1:0];
    wire [W-1:0] quo_next = {quo[W-2:0], fits};
    wire last = busy && count == LAST;
    // Mutation 2 gives the remainder the sign of the quotient instead of the dividend.
    wire negate_r = MUTATION == 2 ? neg_q : neg_r;

    always @(posedge clk) begin
        if (!rst_n) begin
            busy <= 0; out_valid <= 0; count <= 0; neg_q <= 0; neg_r <= 0;
            divisor <= 0; quo <= 0; rem <= 0; out_quotient <= 0; out_remainder <= 0;
        end else if (flush && !(MUTATION == 4 && last)) begin  // mutation 4: completion beats flush
            busy <= 0; out_valid <= 0;
        end else if (in_valid && in_ready) begin
            if (zero) begin
                out_valid <= 1; out_quotient <= MUTATION == 1 ? {W{1'b0}} : {W{1'b1}}; out_remainder <= in_dividend;
            end else if (overflow) begin
                out_valid <= 1; out_quotient <= in_dividend; out_remainder <= 0;
            end else if (lesser) begin
                out_valid <= 1; out_quotient <= 0; out_remainder <= in_dividend;
            end else begin
                busy <= 1; count <= 0; divisor <= b_mag; quo <= a_mag; rem <= 0;
                neg_q <= a_neg ^ b_neg; neg_r <= a_neg;
            end
        end else if (busy) begin
            quo <= quo_next; rem <= rem_next; count <= count + 1'b1;
            if (last) begin
                busy <= 0; out_valid <= 1;
                out_quotient <= neg_q ? -quo_next : quo_next;
                out_remainder <= negate_r ? -rem_next : rem_next;
            end
        end else if (out_valid && out_ready) begin
            out_valid <= 0;
        end
    end

`ifdef FORMAL
    // The operands of the accepted division, kept beside the design, and the results that
    // Verilog's / and % give for them. Special cases follow the RISC-V M extension.
    reg f_past = 0, f_signed = 0;
    reg [W-1:0] f_a = 0, f_b = 0;
    reg [CW+1:0] f_age = 0;
    reg f_pending = 0;  // accepted, not yet shown as a result, and not discarded
    always @(posedge clk) begin
        f_past <= 1;
        if (in_valid && in_ready) begin
            f_a <= in_dividend; f_b <= in_divisor; f_signed <= in_signed; f_age <= 1;
        end else if (f_age != {CW+2{1'b1}}) f_age <= f_age + 1'b1;
        if (!rst_n || flush) f_pending <= 0;
        else if (in_valid && in_ready) f_pending <= 1;
        else if (out_valid) f_pending <= 0;
    end
    wire signed [W-1:0] f_sa = f_a, f_sb = f_b;
    wire signed [W-1:0] f_sq = f_sa / f_sb, f_sr = f_sa % f_sb;
    wire [W-1:0] f_uq = f_a / f_b, f_ur = f_a % f_b;
    wire [W-1:0] spec_q = f_b == 0 ? {W{1'b1}} : f_signed ? f_sq : f_uq;
    wire [W-1:0] spec_r = f_b == 0 ? f_a : f_signed ? f_sr : f_ur;
    wire f_aneg = f_signed && f_a[W-1], f_bneg = f_signed && f_b[W-1];
    wire [W-1:0] f_amag = f_aneg ? -f_a : f_a, f_bmag = f_bneg ? -f_b : f_b;
    wire f_short = f_b == 0 || (f_signed && f_a == MIN && &f_b) || f_amag < f_bmag;
    // Partial result after count steps: the top count bits of |a| divided by |b|, with the
    // remaining low bits still waiting in the upper part of quo.
    wire [2*W-1:0] f_low = (1 << count) - 1;
    wire [2*W-1:0] f_rebuilt = ((divisor * (quo & f_low[W-1:0]) + rem) << (W - count)) + (quo >> count);

    always @(posedge clk) begin
        if (!f_past) as_initial_reset: assume(!rst_n);
        if (f_past) begin
            if (!$past(rst_n)) ap_reset: assert(!busy && !out_valid);
            if ($past(rst_n && flush)) ap_flush: assert(!busy && !out_valid);
            if ($past(rst_n && out_valid && !out_ready && !flush))
                ap_hold: assert(out_valid && $stable(out_quotient) && $stable(out_remainder));
            if (out_valid && !$past(out_valid)) ap_latency: assert(f_age == (f_short ? 1 : W + 1));
            // Every accepted division that is not flushed or reset produces its result.
            if (f_pending && f_age == (f_short ? 1 : W + 1)) ap_completion: assert(out_valid);
            if (out_valid) begin
                ap_quotient: assert(out_quotient == spec_q);
                ap_remainder: assert(out_remainder == spec_r);
            end
            // Auxiliary invariants on the partial result. With them, k-induction closes at
            // depth 2; without them, only at depth W + 3, back from a result to its acceptance.
            ai_exclusive: assert(!(busy && out_valid));
            ai_pending: assert(busy == (f_pending && !out_valid));
            if (busy) begin
                ai_operands: assert(divisor == f_bmag && divisor != 0 && !f_short);
                ai_signs: assert(neg_q == (f_aneg ^ f_bneg) && neg_r == f_aneg);
                ai_age: assert(f_age == count + 1);
                ai_partial: assert(rem < divisor && f_rebuilt == f_amag);
            end
            cp_zero: cover(out_valid && f_b == 0);
            cp_overflow: cover(out_valid && f_signed && f_a == MIN && &f_b);
            cp_equal: cover(out_valid && f_amag == f_bmag && f_a != f_b);
            cp_mixed: cover(out_valid && f_aneg && !f_bneg && out_remainder != 0);
            cp_unsigned_top: cover(out_valid && !f_signed && f_a[W-1] && f_b[W-1] && f_b != f_a);
            cp_hold: cover(out_valid && $past(out_valid) && $past(out_valid, 2));
            cp_flush_last: cover($past(last && flush));
        end
    end
`endif
endmodule
