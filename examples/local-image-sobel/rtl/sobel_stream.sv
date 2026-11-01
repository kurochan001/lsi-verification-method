// Eight-bit grayscale Sobel: |Gx| + |Gy|, saturated to 255, same zero padding.
// conv_window holds two lines and two columns; no frame buffer is stored here.
module sobel_stream #(parameter W=5, H=4, MUTATION=0)(
    input wire clk, rst_n, in_valid,
    input wire [7:0] in_pixel,
    output wire in_ready,
    output reg out_valid,
    input wire out_ready,
    output reg [7:0] out_pixel,
    output reg out_last
);
    wire window_valid, window_last;
    wire [71:0] window_data;
    // Both Sobel kernels have a zero centre coefficient.
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_centre=&{1'b0,window_data[39:32]};
    /* verilator lint_on UNUSEDSIGNAL */
    wire window_ready = !out_valid || out_ready;
    conv_window #(.W(W), .H(H), .STRIDE(1), .MUTATION(MUTATION == 2 ? 1 : 0)) windows(
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_pixel(in_pixel), .in_ready(in_ready),
        .out_valid(window_valid), .out_ready(window_ready), .out_window(window_data), .out_last(window_last));
    integer gx, gy, magnitude;
    always @* begin
        gx = -int'(window_data[7:0]) + int'(window_data[23:16])
             - (MUTATION == 1 ? 1 : 2)*int'(window_data[31:24]) + 2*int'(window_data[47:40])
             - int'(window_data[55:48]) + int'(window_data[71:64]);
        gy = -int'(window_data[7:0]) - 2*int'(window_data[15:8]) - int'(window_data[23:16])
             + int'(window_data[55:48]) + 2*int'(window_data[63:56]) + int'(window_data[71:64]);
        magnitude = (gx < 0 ? -gx : gx) + (gy < 0 ? -gy : gy);
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin out_valid<=0; out_pixel<=0; out_last<=0; end
        else begin
            if (window_ready) begin
                out_valid<=window_valid;
                if (window_valid) begin
                    out_pixel<=magnitude > 255 ? 8'd255 : 8'(magnitude);
                    out_last<=window_last ^ (MUTATION == 3);
                end
            end else if (MUTATION == 4) out_pixel<=out_pixel ^ 8'd1;
        end
    end
endmodule
