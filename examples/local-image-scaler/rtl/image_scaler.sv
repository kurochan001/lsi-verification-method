// Eight-bit grayscale resize by a rational ratio, nearest neighbour with centre alignment.
// Output pixel (x, y) of an out_w x out_h frame takes source pixel
//     column floor((2x + 1) * in_w / (2 * out_w)),  row floor((2y + 1) * in_h / (2 * out_h))
// The division is never done. Two integer accumulators per axis are compared instead:
//     ax = (2x + 1) * in_w   and   bx = 2 * out_w * (p + 1)
// Output x takes column p while ax < bx; otherwise p moves on and bx grows by 2 * out_w. Both
// sides are exact integers, so the phase never drifts and comes back exactly every out_w / g
// outputs (g the common divisor of the two sizes). Rows use the same rule with ay and by.
//
// Streaming: one source row is stored, then every output row that maps to it is emitted, then
// the next source row is accepted. The sizes are taken from the cfg inputs when the first pixel
// of a frame is accepted and held until the frame ends. A size of 0 or above MAX_W / MAX_H is
// refused: cfg_error is high and in_ready low while idle. out_last marks the last pixel of a frame.
//
// MUTATION (deliberate faults for the regression):
//   1 column comparison ax <= bx: the exact tie goes to the left neighbour
//   2 top-left alignment for columns (ax starts at 0): floor(x * in_w / out_w)
//   3 the column phase is not restarted at the start of each output row after the first
//   4 row comparison ay <= by: the exact tie goes to the upper neighbour
//   5 accumulators one bit narrower than the largest frame needs
//   6 out_last at the end of every output row
//   7 ignores out_ready: a held pixel is overwritten
//   8 sizes are read from the cfg inputs during the frame instead of being held
//   9 the upper size limits are not checked
module image_scaler #(parameter MAX_W = 12, MAX_H = 12, MUTATION = 0) (
    input  wire       clk, rst_n,
    input  wire [7:0] cfg_in_w, cfg_in_h, cfg_out_w, cfg_out_h,
    input  wire       in_valid,
    input  wire [7:0] in_pixel,
    output wire       in_ready,
    output reg        out_valid,
    input  wire       out_ready,
    output reg  [7:0] out_pixel,
    output reg        out_last,
    output wire       cfg_error,
    output wire       busy
);
    localparam AW = $clog2(MAX_W);
    localparam XA = $clog2((2 * MAX_W + 1) * MAX_W + 1) - (MUTATION == 5 ? 1 : 0);
    localparam YA = $clog2((2 * MAX_H + 1) * MAX_H + 1) - (MUTATION == 5 ? 1 : 0);
    localparam [7:0] MW = MAX_W[7:0];
    localparam [7:0] MH = MAX_H[7:0];
    localparam [1:0] IDLE = 2'd0, FILL = 2'd1, DECIDE = 2'd2, EMIT = 2'd3;

    reg [7:0] line_mem [0:MAX_W-1];
    reg [1:0] state;
    reg [7:0] iw, ih, ow, oh;           // sizes of the frame in progress
    reg [7:0] fx, sr, ox, oy, p;        // fill column, source row, output column and row, source column
    reg [XA-1:0] ax, bx;
    reg [YA-1:0] ay, by;

    wire [7:0] use_iw = MUTATION == 8 ? cfg_in_w : iw;
    wire [7:0] use_ih = MUTATION == 8 ? cfg_in_h : ih;
    wire [7:0] use_ow = MUTATION == 8 ? cfg_out_w : ow;
    wire [7:0] use_oh = MUTATION == 8 ? cfg_out_h : oh;
    wire [XA-1:0] step_x = XA'({use_iw, 1'b0});
    wire [XA-1:0] div_x = XA'({use_ow, 1'b0});
    wire [XA-1:0] start_x = MUTATION == 2 ? {XA{1'b0}} : XA'(use_iw);
    wire [YA-1:0] step_y = YA'({use_ih, 1'b0});
    wire [YA-1:0] div_y = YA'({use_oh, 1'b0});

    wire nonzero = cfg_in_w != 8'd0 && cfg_in_h != 8'd0 && cfg_out_w != 8'd0 && cfg_out_h != 8'd0;
    wire in_range = cfg_in_w <= MW && cfg_in_h <= MH && cfg_out_w <= MW && cfg_out_h <= MH;
    wire cfg_ok = nonzero && (in_range || MUTATION == 9);
    assign in_ready = (state == IDLE && cfg_ok) || state == FILL;
    assign cfg_error = state == IDLE && !cfg_ok;
    assign busy = state != IDLE;

    wire take = in_valid && in_ready;
    wire free = !out_valid || out_ready || MUTATION == 7;
    wire col_here = MUTATION == 1 ? ax <= bx : ax < bx;
    wire row_here = MUTATION == 4 ? ay <= by : ay < by;
    wire row_end = ox == use_ow - 8'd1;
    wire frame_end = row_end && oy == use_oh - 8'd1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE;
            out_valid <= 1'b0;
            out_pixel <= 8'd0;
            out_last <= 1'b0;
            {iw, ih, ow, oh} <= 32'd0;
            {fx, sr, ox, oy, p} <= 40'd0;
            ax <= {XA{1'b0}};
            bx <= {XA{1'b0}};
            ay <= {YA{1'b0}};
            by <= {YA{1'b0}};
        end else begin
            if (out_valid && out_ready) out_valid <= 1'b0;
            case (state)
                IDLE: if (take) begin
                    iw <= cfg_in_w; ih <= cfg_in_h; ow <= cfg_out_w; oh <= cfg_out_h;
                    line_mem[0] <= in_pixel;
                    sr <= 8'd0;
                    oy <= 8'd0;
                    ay <= YA'(cfg_in_h);
                    by <= YA'({cfg_out_h, 1'b0});
                    fx <= 8'd1;
                    state <= cfg_in_w == 8'd1 ? DECIDE : FILL;
                end
                FILL: if (take) begin
                    line_mem[fx[AW-1:0]] <= in_pixel;
                    fx <= fx + 8'd1;
                    if (fx == use_iw - 8'd1) state <= DECIDE;
                end
                DECIDE: begin
                    if (oy < use_oh && row_here) begin          // an output row maps to the stored row
                        ox <= 8'd0;
                        if (MUTATION != 3 || oy == 8'd0) begin
                            p <= 8'd0;
                            ax <= start_x;
                            bx <= div_x;
                        end
                        state <= EMIT;
                    end else if (sr == use_ih - 8'd1) begin   // the last source row is done
                        state <= IDLE;
                    end else begin                             // accept the next source row
                        sr <= sr + 8'd1;
                        by <= by + div_y;
                        fx <= 8'd0;
                        state <= FILL;
                    end
                end
                EMIT: begin
                    if (col_here) begin
                        if (free) begin
                            out_valid <= 1'b1;
                            out_pixel <= line_mem[p[AW-1:0]];
                            out_last <= MUTATION == 6 ? row_end : frame_end;
                            ox <= ox + 8'd1;
                            ax <= ax + step_x;
                            if (row_end) begin
                                oy <= oy + 8'd1;
                                ay <= ay + step_y;
                                state <= DECIDE;
                            end
                        end
                    end else begin
                        p <= p + 8'd1;
                        bx <= bx + div_x;
                    end
                end
            endcase
        end
    end
endmodule
