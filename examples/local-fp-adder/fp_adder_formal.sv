// Reference for the proof, written without the steps of the design: each finite operand becomes
// an exact integer in units of the smallest subnormal number, the two are added or subtracted
// exactly, and the wide result is cut at its leading one and rounded once. There is no
// alignment shift, no guard, round or sticky bit and no renormalization.
// ONLY keeps one of the two assertions (1: the result, 2: the flags), so that a mutant task
// names the assertion that must fail.
module fp_adder_formal #(parameter EXP = 4, FRAC = 3, MUTATION = 0, ONLY = 0) (
    input wire clk, sub,
    input wire [2:0] rm,
    input wire [EXP+FRAC:0] a, b
);
    localparam W = EXP + FRAC + 1;
    localparam MW = FRAC + (1 << EXP);       // enough for the sum of two largest finite numbers
    localparam [EXP-1:0] ONES = {EXP{1'b1}};
    wire [W-1:0] result;
    wire [4:0] flags;
    fp_adder #(.EXP(EXP), .FRAC(FRAC), .MUTATION(MUTATION)) dut(.sub(sub), .rm(rm), .a(a), .b(b), .result(result), .flags(flags));

    function [MW-1:0] units(input [W-1:0] x);   // magnitude of a finite code
        reg [MW-1:0] significand;
        begin
            significand = 0;
            significand[FRAC:0] = {|x[W-2:FRAC], x[FRAC-1:0]};
            units = x[W-2:FRAC] > 1 ? significand << (x[W-2:FRAC] - 1'b1) : significand;
        end
    endfunction
    function is_nan(input [W-1:0] x); is_nan = &x[W-2:FRAC] && |x[FRAC-1:0]; endfunction
    function is_inf(input [W-1:0] x); is_inf = &x[W-2:FRAC] && !(|x[FRAC-1:0]); endfunction

    wire a_sign = a[W-1], b_sign = b[W-1] ^ sub;
    wire [MW-1:0] a_units = units(a), b_units = units(b);
    reg [W-1:0] want;
    reg [4:0] want_flags;
    reg sign, up, tie, above, nonzero;
    reg [MW-1:0] magnitude, remainder, half;
    reg [FRAC+1:0] kept;
    reg [EXP:0] scale;
    integer top, i;
    always @* begin
        want_flags = 0; sign = 0; up = 0; tie = 0; above = 0; nonzero = 0;
        magnitude = 0; remainder = 0; half = 0; kept = 0; scale = 0; top = 0;
        if (is_nan(a) || is_nan(b) || (is_inf(a) && is_inf(b) && a_sign != b_sign)) begin
            want = {1'b0, ONES, 1'b1, {FRAC-1{1'b0}}};
            want_flags[4] = (is_nan(a) && !a[FRAC-1]) || (is_nan(b) && !b[FRAC-1]) || !(is_nan(a) || is_nan(b));
        end else if (is_inf(a) || is_inf(b)) begin
            want = {is_inf(a) ? a_sign : b_sign, ONES, {FRAC{1'b0}}};
        end else begin
            if (a_sign == b_sign) begin magnitude = a_units + b_units; sign = a_sign; end
            else if (a_units >= b_units) begin magnitude = a_units - b_units; sign = a_sign; end
            else begin magnitude = b_units - a_units; sign = b_sign; end
            for (i = 0; i < MW; i = i + 1) if (magnitude[i]) top = i;
            if (magnitude == 0) begin
                want = {a_sign == b_sign ? a_sign : rm == 3'd2, {W-1{1'b0}}};
            end else if (top <= FRAC) begin   // subnormal or in the lowest binade: representable as it is
                want = {sign, {EXP-1{1'b0}}, magnitude[FRAC], magnitude[FRAC-1:0]};
            end else begin
                kept = (FRAC+2)'(magnitude >> (top - FRAC));
                half = {{MW-1{1'b0}}, 1'b1} << (top - FRAC - 1);
                remainder = magnitude & ((half << 1) - 1'b1);
                nonzero = remainder != 0; tie = remainder == half; above = remainder > half;
                case (rm)
                    3'd0: up = above || (tie && kept[0]);
                    3'd1: up = 0;
                    3'd2: up = sign && nonzero;
                    3'd3: up = !sign && nonzero;
                    default: up = above || tie;
                endcase
                kept = kept + {{FRAC+1{1'b0}}, up};
                scale = (EXP+1)'(top - FRAC + 1);
                if (kept[FRAC+1]) begin kept = kept >> 1; scale = scale + 1'b1; end
                want_flags[0] = nonzero;
                if (scale >= {1'b0, ONES}) begin
                    want_flags[2] = 1; want_flags[0] = 1;
                    if (rm == 3'd0 || rm == 3'd4 || (rm == 3'd2 && sign) || (rm == 3'd3 && !sign)) want = {sign, ONES, {FRAC{1'b0}}};
                    else want = {sign, ONES - 1'b1, {FRAC{1'b1}}};
                end else want = {sign, scale[EXP-1:0], kept[FRAC-1:0]};
            end
        end
    end
    always @(posedge clk) begin
        as_mode: assume(rm <= 3'd4);
        cp_tie: cover(tie && rm == 3'd0);
        cp_carry: cover(up && kept == {2'b01, {FRAC{1'b0}}} && nonzero);
        cp_overflow_finite: cover(want_flags[2] && want[W-2:FRAC] != ONES);
        cp_subnormal: cover(want[W-2:FRAC] == 0 && want[FRAC-1:0] != 0);
        cp_negative_zero: cover(want == {1'b1, {W-1{1'b0}}} && a_sign != b_sign);
        cp_invalid_infinities: cover(is_inf(a) && is_inf(b) && want_flags[4]);
        cp_cancellation: cover(a_sign != b_sign && magnitude != 0 && a_units[MW-1:FRAC+3] != 0 && top <= FRAC);
    end
    generate
        if (ONLY != 2) begin : g_result
            always @(posedge clk) ap_result: assert(result == want);
        end
        if (ONLY != 1) begin : g_flags
            always @(posedge clk) ap_flags: assert(flags == want_flags);
        end
    endgenerate
endmodule
