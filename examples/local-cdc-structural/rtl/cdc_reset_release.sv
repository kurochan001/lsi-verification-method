// Negative example: the asynchronous reset reaches the flops without a synchronised release.
// `ready` uses one stage only, which can still pass on a metastable release.
module cdc_reset_release (
    input  wire clk, rst_n,
    input  wire d,
    output wire q, ready
);
    reg q_reg, one_stage, ready_reg;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) q_reg <= 1'b0;
        else q_reg <= d;
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) one_stage <= 1'b0;
        else one_stage <= 1'b1;
    end
    always @(posedge clk or negedge one_stage) begin
        if (!one_stage) ready_reg <= 1'b0;
        else ready_reg <= d;
    end
    assign q = q_reg;
    assign ready = ready_reg;
endmodule
