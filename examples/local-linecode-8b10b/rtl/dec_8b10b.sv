// 8b/10b decoder with its running disparity. The outputs are valid in the cycle of valid.
module dec_8b10b #(parameter MUTATION = 0) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       valid,
    input  wire [9:0] code,
    output wire [7:0] data,
    output wire       k,
    output wire       code_err,
    output wire       disp_err,
    output reg        rd
);
    wire rd_next;
    dec_8b10b_comb #(.MUTATION(MUTATION)) u_comb(.code(code), .rd(rd), .data(data), .k(k),
        .code_err(code_err), .disp_err(disp_err), .rd_next(rd_next));
    always @(posedge clk) begin
        if (!rst_n) rd <= 1'b0;
        else if (valid) rd <= rd_next;
    end
endmodule
