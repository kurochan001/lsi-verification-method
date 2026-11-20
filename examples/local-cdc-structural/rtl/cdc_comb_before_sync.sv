// Negative example: two flops of the a domain are combined before the synchroniser.
// A glitch of the AND gate can be captured by the first stage.
module cdc_comb_before_sync (
    input  wire a_clk, b_clk,
    input  wire a_x_in, a_y_in,
    output wire b_out
);
    reg a_x, a_y;
    reg [1:0] b_sync;
    always @(posedge a_clk) begin
        a_x <= a_x_in;
        a_y <= a_y_in;
    end
    always @(posedge b_clk) b_sync <= {b_sync[0], a_x & a_y};
    assign b_out = b_sync[1];
endmodule
