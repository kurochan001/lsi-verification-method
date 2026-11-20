// Negative example: a flop of the a domain is sampled by one flop of the b domain and used at once.
module cdc_no_sync (
    input  wire a_clk, b_clk,
    input  wire a_in, b_enable,
    output wire b_out
);
    reg a_q, b_q;
    always @(posedge a_clk) a_q <= a_in;
    always @(posedge b_clk) b_q <= a_q;
    assign b_out = b_q & b_enable;
endmodule
