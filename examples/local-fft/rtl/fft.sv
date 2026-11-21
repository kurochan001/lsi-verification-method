// Sequential radix-2 FFT on fixed-point complex samples, N = 2**LOGN points (LOGN 2..6).
//
// A frame is loaded one sample per clock while in_ready is 1 (in_valid without in_ready is
// ignored). The samples are stored in bit-reversed order, the transform then runs in place
// with one butterfly per clock (LOGN * N / 2 clocks), and the N bins come out in natural
// order, one per clock, with out_last on bin N-1. A new frame is accepted after the last bin.
//
// Butterfly of stage s (0-based), on the pair (a, b) that is 2**s apart:
//   t = b * (cos - j sin), rounded half up to an integer (twiddle factors are signed Q1.14)
//   a' = a + t,  b' = a - t
// SCALE != 0 halves a' and b', rounding half up, so the output is the transform divided by N.
// SCALE == 0 leaves them, so the output is the transform itself and grows by up to N.
// A result outside the WIDTH-bit range saturates and sets `overflow`, which stays set until
// the last bin of the frame has gone out. `overflow` is meaningful while out_valid is 1.
//
// Reset (synchronous, active low) drops the frame at any point and returns to loading.
//
// MUTATION: 1 samples are stored without bit reversal, 2 the twiddle angle of every stage is
// doubled, 3 the product truncates instead of rounding, 4 one table entry is one unit too
// large, 5 an overflowing result wraps instead of saturating, 6 `overflow` reports only the
// last butterfly, 7 a sample offered while busy is written into the memory, 8 out_last comes
// one bin early, 9 reset does not clear the sample counter, 10 the lower output of the
// butterfly adds instead of subtracting.
module fft #(
    parameter LOGN = 4,
    parameter WIDTH = 16,
    parameter SCALE = 1,
    parameter MUTATION = 0
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    in_valid,
    output logic                    in_ready,
    input  logic signed [WIDTH-1:0] in_re,
    input  logic signed [WIDTH-1:0] in_im,
    output logic                    out_valid,
    output logic                    out_last,
    output logic signed [WIDTH-1:0] out_re,
    output logic signed [WIDTH-1:0] out_im,
    output logic                    overflow
);
    localparam N = 1 << LOGN;
    localparam FRACTION = 14;
    localparam PW = WIDTH + 17;      // product of a sample and a twiddle component, two of them added
    localparam TW = PW - FRACTION;   // the rounded product
    localparam SW = TW + 1;          // a + t and a - t

    localparam [1:0] LOAD = 2'd0, RUN = 2'd1, SEND = 2'd2;
    localparam [31:0] LAST_STAGE = LOGN - 1;

    // cos(2 pi k / 64) and sin(2 pi k / 64) for half a turn, scaled by 2**14 and rounded.
    function automatic signed [15:0] cos_q14(input [4:0] k);
        case (k)
            5'd0: cos_q14 = 16'sd16384;
            5'd1: cos_q14 = 16'sd16305;
            5'd2: cos_q14 = 16'sd16069;
            5'd3: cos_q14 = 16'sd15679;
            5'd4: cos_q14 = 16'sd15137;
            5'd5: cos_q14 = 16'sd14449;
            5'd6: cos_q14 = 16'sd13623;
            5'd7: cos_q14 = 16'sd12665;
            5'd8: cos_q14 = (MUTATION == 4) ? 16'sd11586 : 16'sd11585;
            5'd9: cos_q14 = 16'sd10394;
            5'd10: cos_q14 = 16'sd9102;
            5'd11: cos_q14 = 16'sd7723;
            5'd12: cos_q14 = 16'sd6270;
            5'd13: cos_q14 = 16'sd4756;
            5'd14: cos_q14 = 16'sd3196;
            5'd15: cos_q14 = 16'sd1606;
            5'd16: cos_q14 = 16'sd0;
            5'd17: cos_q14 = -16'sd1606;
            5'd18: cos_q14 = -16'sd3196;
            5'd19: cos_q14 = -16'sd4756;
            5'd20: cos_q14 = -16'sd6270;
            5'd21: cos_q14 = -16'sd7723;
            5'd22: cos_q14 = -16'sd9102;
            5'd23: cos_q14 = -16'sd10394;
            5'd24: cos_q14 = -16'sd11585;
            5'd25: cos_q14 = -16'sd12665;
            5'd26: cos_q14 = -16'sd13623;
            5'd27: cos_q14 = -16'sd14449;
            5'd28: cos_q14 = -16'sd15137;
            5'd29: cos_q14 = -16'sd15679;
            5'd30: cos_q14 = -16'sd16069;
            5'd31: cos_q14 = -16'sd16305;
            default: cos_q14 = 16'sd0;
        endcase
    endfunction

    function automatic signed [15:0] sin_q14(input [4:0] k);
        case (k)
            5'd0: sin_q14 = 16'sd0;
            5'd1: sin_q14 = 16'sd1606;
            5'd2: sin_q14 = 16'sd3196;
            5'd3: sin_q14 = 16'sd4756;
            5'd4: sin_q14 = 16'sd6270;
            5'd5: sin_q14 = 16'sd7723;
            5'd6: sin_q14 = 16'sd9102;
            5'd7: sin_q14 = 16'sd10394;
            5'd8: sin_q14 = 16'sd11585;
            5'd9: sin_q14 = 16'sd12665;
            5'd10: sin_q14 = 16'sd13623;
            5'd11: sin_q14 = 16'sd14449;
            5'd12: sin_q14 = 16'sd15137;
            5'd13: sin_q14 = 16'sd15679;
            5'd14: sin_q14 = 16'sd16069;
            5'd15: sin_q14 = 16'sd16305;
            5'd16: sin_q14 = 16'sd16384;
            5'd17: sin_q14 = 16'sd16305;
            5'd18: sin_q14 = 16'sd16069;
            5'd19: sin_q14 = 16'sd15679;
            5'd20: sin_q14 = 16'sd15137;
            5'd21: sin_q14 = 16'sd14449;
            5'd22: sin_q14 = 16'sd13623;
            5'd23: sin_q14 = 16'sd12665;
            5'd24: sin_q14 = 16'sd11585;
            5'd25: sin_q14 = 16'sd10394;
            5'd26: sin_q14 = 16'sd9102;
            5'd27: sin_q14 = 16'sd7723;
            5'd28: sin_q14 = 16'sd6270;
            5'd29: sin_q14 = 16'sd4756;
            5'd30: sin_q14 = 16'sd3196;
            5'd31: sin_q14 = 16'sd1606;
            default: sin_q14 = 16'sd0;
        endcase
    endfunction

    // Clamp to WIDTH bits. The second result bit says that the value did not fit.
    function automatic [WIDTH:0] saturate(input signed [SW-1:0] value);
        logic fits;
        begin
            fits = (value[SW-1:WIDTH-1] == '0) || (value[SW-1:WIDTH-1] == '1);
            if (fits || MUTATION == 5) saturate = {!fits, value[WIDTH-1:0]};
            else                       saturate = {1'b1, value[SW-1], {(WIDTH-1){!value[SW-1]}}};
        end
    endfunction

    logic signed [WIDTH-1:0] mem_re [0:N-1];
    logic signed [WIDTH-1:0] mem_im [0:N-1];
    logic [1:0]      state;
    logic [LOGN-1:0] index;   // sample being loaded, or bin being sent
    logic [2:0]      stage;
    logic [LOGN-2:0] pair;    // butterfly within the stage
    logic            flag;

    // Load address: the bits of the sample number in reverse order.
    logic [LOGN-1:0] reversed;
    genvar g;
    generate
        for (g = 0; g < LOGN; g = g + 1) begin : g_reverse
            assign reversed[g] = index[LOGN-1-g];
        end
    endgenerate

    // The two addresses and the twiddle angle of the current butterfly.
    logic [LOGN-1:0] one, pair_wide, low_mask, offset, a, b;
    logic [7:0]      offset_wide, angle;
    assign one = {{(LOGN-1){1'b0}}, 1'b1};
    assign pair_wide = {1'b0, pair};
    assign low_mask = (one << stage) - one;
    assign offset = pair_wide & low_mask;                       // position within the half block
    assign a = ((pair_wide & ~low_mask) << 1) | offset;
    assign b = a | (one << stage);
    assign offset_wide = {{(8-LOGN){1'b0}}, offset};
    assign angle = offset_wide << ((MUTATION == 2 ? 3'd6 : 3'd5) - stage);

    logic signed [15:0]      c, s;
    logic signed [PW-1:0]    c_wide, s_wide, br_wide, bi_wide, half, product_re, product_im;
    logic signed [SW-1:0]    ar, ai, tr, ti, sum_re, sum_im, difference_re, difference_im;
    logic [WIDTH:0]          upper_re, upper_im, lower_re, lower_im;
    assign c = cos_q14(angle[4:0]);
    assign s = sin_q14(angle[4:0]);
    assign c_wide = $signed({{(PW-16){c[15]}}, c});
    assign s_wide = $signed({{(PW-16){s[15]}}, s});
    assign br_wide = $signed({{(PW-WIDTH){mem_re[b][WIDTH-1]}}, mem_re[b]});
    assign bi_wide = $signed({{(PW-WIDTH){mem_im[b][WIDTH-1]}}, mem_im[b]});
    assign half = (MUTATION == 3) ? '0 : ($signed({{(PW-1){1'b0}}, 1'b1}) <<< (FRACTION - 1));
    assign product_re = c_wide * br_wide + s_wide * bi_wide + half;
    assign product_im = c_wide * bi_wide - s_wide * br_wide + half;
    assign tr = $signed({product_re[PW-1], product_re[PW-1:FRACTION]});
    assign ti = $signed({product_im[PW-1], product_im[PW-1:FRACTION]});
    assign ar = $signed({{(SW-WIDTH){mem_re[a][WIDTH-1]}}, mem_re[a]});
    assign ai = $signed({{(SW-WIDTH){mem_im[a][WIDTH-1]}}, mem_im[a]});

    // Halve with rounding half up when the transform is scaled.
    function automatic signed [SW-1:0] scaled(input signed [SW-1:0] value);
        logic signed [SW-1:0] bumped;
        begin
            bumped = value + $signed({{(SW-1){1'b0}}, 1'b1});
            scaled = (SCALE != 0) ? $signed({bumped[SW-1], bumped[SW-1:1]}) : value;
        end
    endfunction

    assign sum_re = scaled(ar + tr);
    assign sum_im = scaled(ai + ti);
    assign difference_re = scaled((MUTATION == 10) ? ar + tr : ar - tr);
    assign difference_im = scaled((MUTATION == 10) ? ai + ti : ai - ti);
    assign upper_re = saturate(sum_re);
    assign upper_im = saturate(sum_im);
    assign lower_re = saturate(difference_re);
    assign lower_im = saturate(difference_im);

    logic overflowing;
    assign overflowing = upper_re[WIDTH] | upper_im[WIDTH] | lower_re[WIDTH] | lower_im[WIDTH];

    // Bits below the rounding point and above the angle are not used.
    wire unused = &{1'b0, product_re[FRACTION-1:0], product_im[FRACTION-1:0], angle[7:5]};

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            state <= LOAD;
            if (MUTATION != 9) index <= '0;
            stage <= 3'd0;
            pair <= '0;
            flag <= 1'b0;
        end else begin
            case (state)
                LOAD: if (in_valid) begin
                    mem_re[(MUTATION == 1) ? index : reversed] <= in_re;
                    mem_im[(MUTATION == 1) ? index : reversed] <= in_im;
                    index <= index + one;        // wraps to 0 after the last sample
                    if (index == '1) begin
                        state <= RUN;
                        stage <= 3'd0;
                        pair <= '0;
                    end
                end
                RUN: begin
                    mem_re[a] <= $signed(upper_re[WIDTH-1:0]);
                    mem_im[a] <= $signed(upper_im[WIDTH-1:0]);
                    mem_re[b] <= $signed(lower_re[WIDTH-1:0]);
                    mem_im[b] <= $signed(lower_im[WIDTH-1:0]);
                    flag <= (MUTATION == 6) ? overflowing : (flag | overflowing);
                    pair <= pair + {{(LOGN-2){1'b0}}, 1'b1};   // wraps to 0 after the last pair
                    if (pair == '1) begin
                        if (stage == LAST_STAGE[2:0]) state <= SEND;
                        else                   stage <= stage + 3'd1;
                    end
                end
                SEND: begin
                    index <= index + one;
                    if (index == '1) begin
                        state <= LOAD;
                        flag <= 1'b0;
                    end
                end
                default: state <= LOAD;
            endcase
            if (MUTATION == 7 && state != LOAD && in_valid) begin
                mem_re[reversed] <= in_re;
                mem_im[reversed] <= in_im;
            end
        end
    end

    assign in_ready = state == LOAD;
    assign out_valid = state == SEND;
    assign out_last = out_valid && (index == ((MUTATION == 8) ? ~one : '1));
    assign out_re = out_valid ? mem_re[index] : '0;
    assign out_im = out_valid ? mem_im[index] : '0;
    assign overflow = flag;
endmodule
