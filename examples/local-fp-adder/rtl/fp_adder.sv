// Floating-point adder and subtractor in the IEEE 754 binary interchange layout, combinational.
// One exponent field of EXP bits and one fraction field of FRAC bits: EXP=8, FRAC=23 is binary32.
// rm uses the RISC-V frm encoding: 0 RNE, 1 RTZ, 2 RDN, 3 RUP, 4 RMM; 5 to 7 are outside the contract.
// flags is {NV, DZ, OF, UF, NX}. DZ and UF are never set: a sum that falls in the subnormal
// range is always exact. Every NaN result is the canonical quiet NaN.
module fp_adder #(parameter EXP = 8, FRAC = 23, MUTATION = 0) (
    input  wire              sub,     // 0: a + b, 1: a - b
    input  wire [2:0]        rm,
    input  wire [EXP+FRAC:0] a, b,
    output reg  [EXP+FRAC:0] result,
    output reg  [4:0]        flags
);
    localparam SW = FRAC + 4;          // significand with hidden bit and guard, round, sticky
    localparam LW = $clog2(SW + 1);
    localparam [2:0] RNE = 3'd0, RTZ = 3'd1, RDN = 3'd2, RUP = 3'd3, RMM = 3'd4;
    localparam [EXP-1:0] EXP_ONES = {EXP{1'b1}};

    wire            a_sign = a[EXP+FRAC];
    wire            b_sign = b[EXP+FRAC] ^ sub;
    wire [EXP-1:0]  a_exp = a[EXP+FRAC-1:FRAC], b_exp = b[EXP+FRAC-1:FRAC];
    wire [FRAC-1:0] a_frac = a[FRAC-1:0], b_frac = b[FRAC-1:0];
    wire a_nan = &a_exp && |a_frac, b_nan = &b_exp && |b_frac;
    wire a_inf = &a_exp && !(|a_frac), b_inf = &b_exp && !(|b_frac);
    wire a_signaling = a_nan && !a_frac[FRAC-1], b_signaling = b_nan && !b_frac[FRAC-1];

    // A subnormal number has the exponent of the smallest normal number and no hidden bit.
    wire [EXP-1:0] a_scale = |a_exp ? a_exp : {{EXP-1{1'b0}}, 1'b1};
    wire [EXP-1:0] b_scale = |b_exp ? b_exp : {{EXP-1{1'b0}}, 1'b1};
    wire [FRAC:0]  a_sig = {|a_exp, a_frac}, b_sig = {|b_exp, b_frac};

    // x is the operand of the larger magnitude.
    wire            swap = {b_scale, b_sig} > {a_scale, a_sig};
    wire            x_sign = swap ? b_sign : a_sign;
    wire [EXP-1:0]  x_scale = swap ? b_scale : a_scale, y_scale = swap ? a_scale : b_scale;
    wire [SW-1:0]   x_ext = {swap ? b_sig : a_sig, 3'b000};
    wire [SW-1:0]   y_ext = {swap ? a_sig : b_sig, 3'b000};
    wire            same_sign = a_sign == b_sign;

    // Align y. Everything shifted out is kept as one sticky bit.
    wire [EXP-1:0]    distance = x_scale - y_scale;
    wire [EXP+LW-1:0] distance_wide = {{LW{1'b0}}, distance};
    wire [EXP+LW-1:0] limit = (EXP+LW)'(SW);
    wire [LW-1:0]     shift = distance_wide >= limit ? limit[LW-1:0] : distance[LW-1:0];
    wire [2*SW-1:0]   aligned = {y_ext, {SW{1'b0}}} >> shift;
    wire              lost = |aligned[SW-1:0] && MUTATION != 1;
    wire [SW-1:0]     y_aligned = {aligned[2*SW-1:SW+1], aligned[SW] | lost};

    wire [SW:0] total = same_sign ? {1'b0, x_ext} + {1'b0, y_aligned} : {1'b0, x_ext} - {1'b0, y_aligned};

    // Normalize: one step right after a carry, otherwise left as far as the exponent allows.
    reg [LW-1:0] zeros;
    integer i;
    always @* begin
        zeros = SW[LW-1:0];
        for (i = 0; i < SW; i = i + 1)
            if (total[i]) zeros = LW'(SW - 1 - i);
    end
    wire [EXP-1:0]    room = x_scale - 1'b1;
    wire [EXP+LW-1:0] zeros_wide = {{EXP{1'b0}}, zeros}, room_wide = {{LW{1'b0}}, room};
    wire [LW-1:0]     left = zeros_wide < room_wide ? zeros : room[LW-1:0];
    wire [SW-1:0]     normalized = total[SW] ? {total[SW:2], total[1] | total[0]} : total[SW-1:0] << left;
    wire [EXP:0]      scale = total[SW] ? {1'b0, x_scale} + 1'b1 : {1'b0, x_scale} - {{EXP+1-LW{1'b0}}, left};

    // Round.
    wire [FRAC:0] kept = normalized[SW-1:3];
    wire          guard = normalized[2], rest = normalized[1] | normalized[0];
    wire          inexact = guard | rest;
    reg           up;
    always @* begin
        case (rm)
            RTZ: up = 1'b0;
            RDN: up = x_sign && inexact;
            RUP: up = !x_sign && inexact;
            RMM: up = guard;
            default: up = guard && (rest || kept[0] || MUTATION == 2);
        endcase
    end
    wire [FRAC+1:0] rounded = {1'b0, kept} + {{FRAC+1{1'b0}}, up};
    wire            carry = rounded[FRAC+1];
    wire [FRAC:0]   significand = carry ? rounded[FRAC+1:1] : rounded[FRAC:0];
    wire [EXP:0]    final_scale = scale + {{EXP{1'b0}}, carry && MUTATION != 4};
    wire            overflow = significand[FRAC] && final_scale >= {1'b0, EXP_ONES};
    wire            to_infinity = rm == RNE || rm == RMM || (rm == RDN && x_sign) || (rm == RUP && !x_sign) || MUTATION == 6;
    wire            zero_sign = same_sign ? a_sign : rm == RDN && MUTATION != 5;
    wire [EXP-1:0]  exponent = significand[FRAC] || MUTATION == 3 ? final_scale[EXP-1:0] : {EXP{1'b0}};

    always @* begin
        flags = 5'b00000;
        if (a_nan || b_nan || (a_inf && b_inf && !same_sign)) begin
            result = {1'b0, EXP_ONES, 1'b1, {FRAC-1{1'b0}}};
            flags[4] = a_signaling || b_signaling || !(a_nan || b_nan);
        end else if (a_inf || b_inf) begin
            result = {a_inf ? a_sign : b_sign, EXP_ONES, {FRAC{1'b0}}};
        end else if (overflow) begin
            result = to_infinity ? {x_sign, EXP_ONES, {FRAC{1'b0}}} : {x_sign, EXP_ONES - 1'b1, {FRAC{1'b1}}};
            flags[2] = 1'b1;
            flags[0] = 1'b1;
        end else if (!(|significand)) begin
            result = {zero_sign, {EXP+FRAC{1'b0}}};
        end else begin
            result = {x_sign, exponent, significand[FRAC-1:0]};
            flags[0] = MUTATION == 7 ? guard : inexact;
        end
    end
endmodule
