// Positive example: every crossing goes through a two-flop synchroniser, and each domain
// releases its asynchronous reset through its own two-stage reset synchroniser.
module cdc_good (
    input  wire a_clk, b_clk, rst_n,
    input  wire a_level_in, a_event,
    input  wire b_busy_in,
    output wire a_busy,
    output wire b_level,
    output wire b_pulse
);
    reg a_rst_meta, a_rst_n, b_rst_meta, b_rst_n;
    reg a_level, a_toggle, b_busy;
    reg [1:0] b_level_sync, b_toggle_sync, a_busy_sync;
    reg b_toggle_seen;

    always @(posedge a_clk or negedge rst_n) begin
        if (!rst_n) begin
            a_rst_meta <= 1'b0; a_rst_n <= 1'b0;
        end else begin
            a_rst_meta <= 1'b1; a_rst_n <= a_rst_meta;
        end
    end
    always @(posedge b_clk or negedge rst_n) begin
        if (!rst_n) begin
            b_rst_meta <= 1'b0; b_rst_n <= 1'b0;
        end else begin
            b_rst_meta <= 1'b1; b_rst_n <= b_rst_meta;
        end
    end

    always @(posedge a_clk or negedge a_rst_n) begin
        if (!a_rst_n) begin
            a_level <= 1'b0; a_toggle <= 1'b0; a_busy_sync <= 2'b00;
        end else begin
            a_level <= a_level_in;
            if (a_event) a_toggle <= ~a_toggle;
            a_busy_sync <= {a_busy_sync[0], b_busy};
        end
    end

    always @(posedge b_clk or negedge b_rst_n) begin
        if (!b_rst_n) begin
            b_level_sync <= 2'b00; b_toggle_sync <= 2'b00; b_toggle_seen <= 1'b0; b_busy <= 1'b0;
        end else begin
            b_level_sync <= {b_level_sync[0], a_level};
            b_toggle_sync <= {b_toggle_sync[0], a_toggle};
            b_toggle_seen <= b_toggle_sync[1];
            b_busy <= b_busy_in;
        end
    end

    assign a_busy = a_busy_sync[1];
    assign b_level = b_level_sync[1];
    assign b_pulse = b_toggle_sync[1] ^ b_toggle_seen;
endmodule
