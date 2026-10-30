// 3x3 window generator for a W x H raster stream, with zero padding ("same") and
// a stride. The window centred on pixel k is complete once pixel k+W+1 has arrived,
// so each step completes at most one window. After the last pixel of a frame,
// W+1 flush steps complete the remaining windows from zero padding; new pixels
// wait during the flush.
module conv_window #(parameter W=5, H=4, STRIDE=1, MUTATION=0)(
    input wire clk, rst_n,
    input wire in_valid, input wire [7:0] in_pixel, output wire in_ready,
    output reg out_valid, input wire out_ready, output reg [71:0] out_window, output reg out_last);
    localparam STEPS = W*H + W + 1;
    localparam LAST_ROW = ((H-1)/STRIDE)*STRIDE, LAST_COL = ((W-1)/STRIDE)*STRIDE;
    reg [7:0] line [0:2*W-1];  // line[k]: the pixel of k+1 steps ago
    reg [23:0] older, newer;   // previous two columns {row i, row i-1, row i-2}
    integer p, row, col;       // step in the frame; centre completed by this step
    wire flushing = p >= W*H;
    wire enable = !out_valid || out_ready;
    assign in_ready = rst_n && enable && !flushing;
    wire step = flushing ? (enable || MUTATION == 4) : in_valid && in_ready;
    wire [7:0] pixel = flushing ? 8'd0 : in_pixel;
    wire [23:0] column = {pixel, line[W-1], line[2*W-1]};
    wire complete = p >= W + 1;
    wire emit = complete && row % STRIDE == 0 && col % STRIDE == 0;
    reg [71:0] window;
    reg [23:0] source;
    integer dr, dc, r, c;
    always @* begin
        for (dr = 0; dr < 3; dr = dr + 1)
            for (dc = 0; dc < 3; dc = dc + 1) begin
                source = dc == 0 ? older : dc == 1 ? newer : column;
                r = row + dr - 1;
                c = col + dc - 1;
                if (r < 0 || r >= H || (c < 0 && MUTATION != 1) || (c >= W && MUTATION != 2))
                    window[8*(3*dr + dc) +: 8] = 8'd0;
                else
                    window[8*(3*dr + dc) +: 8] = source[8*dr +: 8];
            end
    end
    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            p <= 0; row <= 0; col <= 0; older <= 0; newer <= 0;
            out_valid <= 0; out_window <= 0; out_last <= 0;
            for (k = 0; k < 2*W; k = k + 1) line[k] <= 0;
        end else begin
            if (out_valid && out_ready) out_valid <= 0;
            if (step) begin
                line[0] <= pixel;
                for (k = 1; k < 2*W; k = k + 1) line[k] <= line[k-1];
                older <= newer;
                newer <= column;
                if (emit) begin
                    out_valid <= 1; out_window <= window; out_last <= row == LAST_ROW && col == LAST_COL;
                end
                if (p == STEPS - 1 - (MUTATION == 3)) begin
                    p <= 0; row <= 0; col <= 0;
                end else begin
                    p <= p + 1;
                    if (complete) begin
                        if (col == W - 1) begin col <= 0; row <= row + 1; end
                        else col <= col + 1;
                    end
                end
            end
        end
    end
endmodule
