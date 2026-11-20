// Negative example: two signals are synchronised separately and then combined.
// Their arrival can differ by a cycle, so the combination can show a value that never existed.
module cdc_reconvergence (
    input  wire a_clk, b_clk,
    input  wire a_request_in, a_last_in,
    output wire b_final_request
);
    reg a_request, a_last;
    reg [1:0] b_request_sync, b_last_sync;
    reg b_final;
    always @(posedge a_clk) begin
        a_request <= a_request_in;
        a_last <= a_last_in;
    end
    always @(posedge b_clk) begin
        b_request_sync <= {b_request_sync[0], a_request};
        b_last_sync <= {b_last_sync[0], a_last};
        b_final <= b_request_sync[1] & b_last_sync[1];
    end
    assign b_final_request = b_final;
endmodule
