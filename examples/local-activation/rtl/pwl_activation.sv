// Piecewise-linear sigmoid (FUNC=0, input Q3.8) or tanh (FUNC=1, input Q2.9).
// The output is scaled by 1024. Only |x| is approximated: 64 segments of 32 input
// steps between knots, interpolated with rounding; the negative half uses the
// symmetry sigmoid(-x) = 1 - sigmoid(x) or tanh(-x) = -tanh(x). The knot values are
// round(1024 * f(knot)) computed in double precision when the design was written.
module pwl_activation #(parameter FUNC=0, MUTATION=0)(
    input wire clk, rst_n,
    input wire in_valid, input wire [11:0] in_x, output wire in_ready,
    output reg out_valid, input wire out_ready, output reg [11:0] out_y);
    localparam [65*11-1:0] SIGMOID = {
        11'd1024, 11'd1024, 11'd1024, 11'd1024, 11'd1023, 11'd1023, 11'd1023, 11'd1023, 11'd1023, 11'd1023, 11'd1023,
        11'd1023, 11'd1022, 11'd1022, 11'd1022, 11'd1022, 11'd1021, 11'd1021, 11'd1021, 11'd1020, 11'd1020, 11'd1019,
        11'd1019, 11'd1018, 11'd1017, 11'd1016, 11'd1015, 11'd1014, 11'd1013, 11'd1011, 11'd1010, 11'd1008, 11'd1006,
        11'd1003, 11'd1000, 11'd997, 11'd994, 11'd990, 11'd986, 11'd981, 11'd975, 11'd969, 11'd962, 11'd955,
        11'd946, 11'd937, 11'd926, 11'd915, 11'd902, 11'd888, 11'd872, 11'd856, 11'd837, 11'd817, 11'd796,
        11'd773, 11'd749, 11'd723, 11'd695, 11'd667, 11'd637, 11'd607, 11'd576, 11'd544, 11'd512};
    localparam [65*11-1:0] TANH = {
        11'd1023, 11'd1023, 11'd1023, 11'd1023, 11'd1023, 11'd1023, 11'd1023, 11'd1022, 11'd1022, 11'd1022, 11'd1022,
        11'd1021, 11'd1021, 11'd1021, 11'd1020, 11'd1020, 11'd1019, 11'd1018, 11'd1018, 11'd1017, 11'd1016, 11'd1015,
        11'd1013, 11'd1012, 11'd1010, 11'd1008, 11'd1006, 11'd1004, 11'd1001, 11'd999, 11'd995, 11'd991, 11'd987,
        11'd982, 11'd977, 11'd971, 11'd964, 11'd956, 11'd948, 11'd938, 11'd927, 11'd915, 11'd901, 11'd886,
        11'd869, 11'd850, 11'd829, 11'd805, 11'd780, 11'd752, 11'd721, 11'd687, 11'd650, 11'd611, 11'd568,
        11'd522, 11'd473, 11'd421, 11'd367, 11'd310, 11'd251, 11'd190, 11'd127, 11'd64, 11'd0};
    localparam [65*11-1:0] KNOTS = FUNC == 0 ? SIGMOID : TANH;

    wire negative = in_x[11];
    wire [11:0] magnitude = negative ? -in_x : in_x;         // -2048 stays 12'h800
    wire [10:0] a = MUTATION == 4 ? magnitude[10:0] :          // mutation: -2048 wraps to 0
                    magnitude[11] ? 11'd2047 : magnitude[10:0];
    wire [5:0] segment = a[10:5];
    wire [4:0] fraction = MUTATION == 3 ? {1'b0, a[4:1]} : a[4:0];
    wire [10:0] low = KNOTS[11*segment +: 11];
    wire [10:0] high = KNOTS[11*(segment+1) +: 11];
    wire [15:0] step = (high - low) * fraction + (MUTATION == 2 ? 16'd0 : 16'd16);
    wire [10:0] half = low + step[15:5];                       // f(|x|) for x >= 0
    wire [11:0] mirrored = FUNC == 0 ? (MUTATION == 1 ? 12'd1023 : 12'd1024) - half
                                     : (MUTATION == 1 ? ~{1'b0, half} : -{1'b0, half});
    assign in_ready = rst_n && (!out_valid || out_ready);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_valid <= 0; out_y <= 0;
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) out_y <= negative ? mirrored : {1'b0, half};
        end
    end
endmodule
