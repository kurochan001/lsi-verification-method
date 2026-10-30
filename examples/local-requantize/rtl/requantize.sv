// Per-channel INT32 -> INT8 requantization with two rounding steps:
//   t = (x * m + nudge) / 2^31, truncated   ties toward +infinity (doubling high multiply)
//   q = t / 2^s                            ties away from zero  (rounding divide by 2^s)
//   y = clamp(q + zero_point, ACT_MIN, ACT_MAX)
// Three elastic stages; the parameters of a channel are captured with the data
// on the edge that accepts it, so later writes never reach data in flight.
module requantize #(parameter CH=2, ACT_MIN=-128, ACT_MAX=127, MUTATION=0)(
    input wire clk, rst_n,
    input wire cfg_valid, input wire [$clog2(CH)-1:0] cfg_ch, input wire [30:0] cfg_mult,
    input wire [4:0] cfg_shift, input wire [7:0] cfg_zp,
    input wire in_valid, input wire [$clog2(CH)-1:0] in_ch, input wire [31:0] in_x,
    output wire in_ready,
    output wire out_valid, input wire out_ready, output reg [7:0] out_data, output reg out_sat);
    localparam signed [63:0] HALF = 64'sd1073741824;  // 2^30
    reg [30:0] mult [0:CH-1];
    reg [4:0] shift [0:CH-1];
    reg signed [7:0] zp [0:CH-1];
    reg v0, v1, v2;
    reg signed [31:0] t0;
    reg [4:0] s0;
    reg signed [7:0] zp0, zp1;
    reg [$clog2(CH)-1:0] ch0, ch1;
    reg signed [32:0] q1;
    wire ready2 = !v2 || out_ready;
    wire ready1 = !v1 || ready2;
    wire ready0 = !v0 || ready1;
    assign in_ready = rst_n && ready0;
    assign out_valid = v2;

    // Stage 0: doubling high multiply. Truncation toward zero after the nudge
    // makes a negative tie such as -0.5 become 0.
    wire signed [63:0] ab = $signed(in_x) * $signed({1'b0, mult[in_ch]});
    wire signed [63:0] nudged = ab + (ab >= 0 ? HALF : 64'sd1 - HALF);
    wire signed [63:0] nudged_mag = nudged < 0 ? -nudged : nudged;
    wire signed [63:0] high = nudged < 0 ? -(nudged_mag >>> 31) : nudged_mag >>> 31;
    wire signed [63:0] ab_mag = ab < 0 ? -ab : ab;
    wire signed [63:0] symmetric = ab < 0 ? -((ab_mag + HALF) >>> 31) : (ab_mag + HALF) >>> 31;
    wire signed [31:0] t_next = MUTATION == 1 ? symmetric[31:0] : high[31:0];

    // Stage 1: rounding divide by 2^s.
    wire [4:0] s_use = MUTATION == 4 ? shift[ch0] : s0;
    wire [31:0] mask = (32'd1 << s_use) - 32'd1;
    wire [31:0] remainder = t0 & mask;
    wire [31:0] threshold = (mask >> 1) + ((t0 < 0 && MUTATION != 2) ? 32'd1 : 32'd0);
    wire signed [32:0] q_next = (t0 >>> s_use) + (remainder > threshold ? 33'sd1 : 33'sd0);

    // Stage 2: zero point and activation range on the full-width value.
    wire signed [7:0] zp_use = MUTATION == 4 ? zp[ch1] : zp1;
    wire signed [33:0] sum = q1 + zp_use;
    wire signed [33:0] narrowed = $signed(sum[7:0]);
    wire signed [33:0] u = MUTATION == 3 ? narrowed : sum;

    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            v0 <= 0; v1 <= 0; v2 <= 0; t0 <= 0; s0 <= 0; zp0 <= 0; zp1 <= 0;
            ch0 <= 0; ch1 <= 0; q1 <= 0; out_data <= 0; out_sat <= 0;
            for (k = 0; k < CH; k = k + 1) begin mult[k] <= 0; shift[k] <= 0; zp[k] <= 0; end
        end else begin
            if (cfg_valid) begin
                mult[cfg_ch] <= cfg_mult; shift[cfg_ch] <= cfg_shift; zp[cfg_ch] <= cfg_zp;
            end
            if (ready2) begin
                v2 <= v1;
                if (v1) begin
                    if (u < ACT_MIN) begin out_data <= ACT_MIN; out_sat <= 1; end
                    else if (u > ACT_MAX) begin out_data <= ACT_MAX; out_sat <= 1; end
                    else begin out_data <= u[7:0]; out_sat <= 0; end
                end
            end
            if (ready1) begin
                v1 <= v0;
                if (v0) begin q1 <= q_next; zp1 <= zp0; ch1 <= ch0; end
            end
            if (ready0) begin
                v0 <= in_valid;
                if (in_valid) begin t0 <= t_next; s0 <= shift[in_ch]; zp0 <= zp[in_ch]; ch0 <= in_ch; end
            end
        end
    end
endmodule
