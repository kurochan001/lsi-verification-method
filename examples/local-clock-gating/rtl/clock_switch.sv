// Glitch-free switch between two unrelated clocks. Each clock has an enable that is
// requested only after the other enable is off, taken on a rising edge and applied on
// the following falling edge, so a gate opens and closes while its own clock is low.
// MUTATION 3 is a plain multiplexer; MUTATION 4 does not wait for the other enable.
module clock_switch #(parameter integer MUTATION = 0) (
    input  wire clk_a,
    input  wire clk_b,
    input  wire arst_n,
    input  wire sel,        // 0: clk_a, 1: clk_b
    output wire clk_out,
    output wire active_a,
    output wire active_b
);
    reg a_request, a_enable, b_request, b_enable;
    wire a_wanted = !sel && ((MUTATION == 4) || !b_enable);
    wire b_wanted = sel && ((MUTATION == 4) || !a_enable);

    always @(posedge clk_a or negedge arst_n) begin
        if (!arst_n) a_request <= 1'b0;
        else a_request <= a_wanted;
    end
    always @(negedge clk_a or negedge arst_n) begin
        if (!arst_n) a_enable <= 1'b0;
        else a_enable <= a_request;
    end
    always @(posedge clk_b or negedge arst_n) begin
        if (!arst_n) b_request <= 1'b0;
        else b_request <= b_wanted;
    end
    always @(negedge clk_b or negedge arst_n) begin
        if (!arst_n) b_enable <= 1'b0;
        else b_enable <= b_request;
    end

    assign clk_out = (MUTATION == 3) ? (sel ? clk_b : clk_a)
                                     : ((clk_a & a_enable) | (clk_b & b_enable));
    assign active_a = a_enable;
    assign active_b = b_enable;
endmodule
