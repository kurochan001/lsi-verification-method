// 8b/10b encoder with its running disparity. The code is valid in the cycle of valid.
// An illegal control request raises k_err, sends nothing useful and leaves the disparity alone.
module enc_8b10b #(parameter MUTATION = 0) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       valid,
    input  wire       k,
    input  wire [7:0] data,
    output wire [9:0] code,
    output wire       k_err,
    output reg        rd
);
    wire rd_next;
    enc_8b10b_comb #(.MUTATION(MUTATION)) u_comb(.data(data), .k(k), .rd(rd), .code(code), .rd_next(rd_next), .k_err(k_err));
    always @(posedge clk) begin
        if (!rst_n) rd <= 1'b0;
        else if (valid) rd <= rd_next;
    end
endmodule
