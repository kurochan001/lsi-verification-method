// Pipelined CORDIC, one operation per clock, fixed latency of ITER + 2 clocks.
//
// mode 0, rotation : (x_out, y_out) = (x_in, y_in) turned by the angle z_in. z_out is the
//                    angle that the iterations left unturned (close to 0).
// mode 1, vectoring: x_out = sqrt(x_in**2 + y_in**2), z_out = atan2(y_in, x_in). y_out is the
//                    part of y that the iterations left (close to 0).
//
// Angles are 16 bits for one turn: 16'h4000 is 90 degrees, 16'h8000 is 180 degrees.
// x and y are signed WIDTH bits in, signed WIDTH + 1 bits out (a rotated vector can be
// sqrt(2) times longer than its largest component).
//
// Stage 0 folds the input into the half plane in which the iterations converge
// (rotation: an angle outside [-90, 90) degrees turns the vector by 180 degrees first;
// vectoring: a vector with x < 0 is turned by 180 degrees first).
// Stages 1..ITER are the iterations, with GUARD (at least 1) extra low bits on x, y and the angle.
// The last stage multiplies by 1/gain (K / 2**17) and rounds half up.
//
// MUTATION: 1 the last iteration does nothing, 2 the fold negates x only, 3 the angle step of
// iteration 3 is one 16-bit angle unit too large, 4 the gain correction truncates instead of rounding,
// 5 vectoring turns the wrong way, 6 out_valid comes one clock early.
module cordic #(
    parameter WIDTH = 16,
    parameter ITER = 16,
    parameter GUARD = 4,
    parameter MUTATION = 0
) (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    in_valid,
    input  logic                    mode,
    input  logic signed [WIDTH-1:0] x_in,
    input  logic signed [WIDTH-1:0] y_in,
    input  logic [15:0]             z_in,
    output logic                    out_valid,
    output logic signed [WIDTH:0]   x_out,
    output logic signed [WIDTH:0]   y_out,
    output logic [15:0]             z_out
);
    localparam IW = WIDTH + GUARD + 3;   // sign, sqrt(2) and the gain of 1.647 need three more bits
    localparam ZW = 16 + GUARD;
    localparam KF = 17;

    // atan(2**-i) as a fraction of one turn, scaled by 2**32 and rounded.
    function automatic [31:0] atan32(input integer i);
        case (i)
            0: atan32 = 32'd536870912;
            1: atan32 = 32'd316933406;
            2: atan32 = 32'd167458907;
            3: atan32 = 32'd85004756;
            4: atan32 = 32'd42667331;
            5: atan32 = 32'd21354465;
            6: atan32 = 32'd10679838;
            7: atan32 = 32'd5340245;
            8: atan32 = 32'd2670163;
            9: atan32 = 32'd1335087;
            10: atan32 = 32'd667544;
            11: atan32 = 32'd333772;
            12: atan32 = 32'd166886;
            13: atan32 = 32'd83443;
            14: atan32 = 32'd41722;
            15: atan32 = 32'd20861;
            16: atan32 = 32'd10430;
            17: atan32 = 32'd5215;
            18: atan32 = 32'd2608;
            default: atan32 = 32'd1304;
        endcase
    endfunction

    // The angle step of iteration i in units of 2**-ZW of a turn, rounded to nearest.
    function automatic [31:0] step32(input integer i);
        step32 = ((atan32(i) + (32'd1 << (31 - ZW))) >> (32 - ZW)) + ((MUTATION == 3 && i == 3) ? (32'd1 << GUARD) : 32'd0);
    endfunction

    // round(2**17 / gain) for the number of iterations.
    function automatic [KF:0] gain_inverse(input integer n);
        case (n)
            1: gain_inverse = 18'd92682;
            2: gain_inverse = 18'd82897;
            3: gain_inverse = 18'd80422;
            4: gain_inverse = 18'd79801;
            5: gain_inverse = 18'd79646;
            6: gain_inverse = 18'd79607;
            7: gain_inverse = 18'd79597;
            8: gain_inverse = 18'd79595;
            default: gain_inverse = 18'd79594;
        endcase
    endfunction

    localparam [KF:0] K = gain_inverse(ITER);

    logic signed [IW-1:0] x [0:ITER];
    logic signed [IW-1:0] y [0:ITER];
    logic signed [ZW-1:0] z [0:ITER];
    logic                 m [0:ITER];
    logic [ITER+1:0]      valid;

    // Stage 0: sign extension, guard bits and the fold.
    logic                 fold;
    logic signed [IW-1:0] x_wide;
    logic signed [IW-1:0] y_wide;
    logic [15:0]          z_folded;

    assign fold = mode ? x_in[WIDTH-1] : (z_in[15] ^ z_in[14]);
    assign x_wide = $signed({{3{x_in[WIDTH-1]}}, x_in, {GUARD{1'b0}}});
    assign y_wide = $signed({{3{y_in[WIDTH-1]}}, y_in, {GUARD{1'b0}}});
    assign z_folded = mode ? {fold, 15'd0} : {z_in[15] ^ fold, z_in[14:0]};

    always_ff @(posedge clk) begin
        x[0] <= fold ? -x_wide : x_wide;
        y[0] <= (fold && MUTATION != 2) ? -y_wide : y_wide;
        z[0] <= $signed({z_folded, {GUARD{1'b0}}});
        m[0] <= mode;
    end

    // Stages 1..ITER.
    genvar i;
    generate
        for (i = 0; i < ITER; i = i + 1) begin : g_iteration
            localparam [31:0] STEP32 = step32(i);
            localparam signed [ZW-1:0] STEP = $signed(STEP32[ZW-1:0]);
            logic turn_up;   // 1: turn counterclockwise by atan(2**-i)
            assign turn_up = m[i] ? (y[i][IW-1] ^ (MUTATION == 5)) : !z[i][ZW-1];
            always_ff @(posedge clk) begin
                if (MUTATION == 1 && i == ITER - 1) begin
                    x[i+1] <= x[i];
                    y[i+1] <= y[i];
                    z[i+1] <= z[i];
                end else if (turn_up) begin
                    x[i+1] <= x[i] - (y[i] >>> i);
                    y[i+1] <= y[i] + (x[i] >>> i);
                    z[i+1] <= z[i] - STEP;
                end else begin
                    x[i+1] <= x[i] + (y[i] >>> i);
                    y[i+1] <= y[i] - (x[i] >>> i);
                    z[i+1] <= z[i] + STEP;
                end
                m[i+1] <= m[i];
            end
        end
    endgenerate

    // Last stage: gain correction with rounding, and the angle without its guard bits.
    localparam PW = IW + KF + 1;
    logic signed [PW-1:0] half;
    logic signed [PW-1:0] x_scaled;
    logic signed [PW-1:0] y_scaled;
    logic signed [ZW:0]   z_rounded;

    assign half = (MUTATION == 4) ? '0 : ($signed({{(PW-1){1'b0}}, 1'b1}) <<< (KF + GUARD - 1));
    assign x_scaled = x[ITER] * $signed({1'b0, K}) + half;
    assign y_scaled = y[ITER] * $signed({1'b0, K}) + half;
    assign z_rounded = {z[ITER][ZW-1], z[ITER]} + $signed({{(ZW + 1 - GUARD){1'b0}}, 1'b1, {(GUARD-1){1'b0}}});

    // The bits below the rounding point and above the output range are not outputs.
    wire unused_scaled = &{1'b0, x_scaled[PW-1:KF+GUARD+WIDTH+1], x_scaled[KF+GUARD-1:0],
                           y_scaled[PW-1:KF+GUARD+WIDTH+1], y_scaled[KF+GUARD-1:0],
                           z_rounded[ZW], z_rounded[GUARD-1:0]};

    always_ff @(posedge clk) begin
        x_out <= x_scaled[KF+GUARD+WIDTH:KF+GUARD];
        y_out <= y_scaled[KF+GUARD+WIDTH:KF+GUARD];
        z_out <= z_rounded[ZW-1:GUARD];
    end

    always_ff @(posedge clk) begin
        if (!rst_n) valid <= '0;
        else        valid <= {valid[ITER:0], in_valid};
    end

    assign out_valid = (MUTATION == 6) ? valid[ITER] : valid[ITER+1];
endmodule
