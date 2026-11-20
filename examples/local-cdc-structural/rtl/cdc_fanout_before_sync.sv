// Negative example: one flop of the a domain goes to two synchronisers of the b domain.
// The two copies can change in different cycles.
module cdc_fanout_before_sync (
    input  wire a_clk, b_clk,
    input  wire a_in,
    output wire b_start, b_count_enable
);
    reg a_q;
    reg [1:0] b_start_sync, b_enable_sync;
    always @(posedge a_clk) a_q <= a_in;
    always @(posedge b_clk) begin
        b_start_sync <= {b_start_sync[0], a_q};
        b_enable_sync <= {b_enable_sync[0], a_q};
    end
    assign b_start = b_start_sync[1];
    assign b_count_enable = b_enable_sync[1];
endmodule
