// Divide by an odd number with a 50% duty cycle: a rising-edge phase that is high for
// DIV/2 (rounded down) periods, and a copy of it half a period later. Their OR is high
// for DIV/2 periods. MUTATION 5 uses the rising-edge phase alone.
module odd_divider #(parameter integer DIV = 3, parameter integer MUTATION = 0) (
    input  wire clk,
    input  wire arst_n,
    output wire clk_out
);
    localparam integer W = $clog2(DIV);
    localparam [W-1:0] HIGH = W'(DIV / 2);
    localparam [W-1:0] LAST = W'(DIV - 1);
    reg [W-1:0] count;
    reg rise_phase, fall_phase;

    always @(posedge clk or negedge arst_n) begin
        if (!arst_n) begin
            count <= {W{1'b0}};
            rise_phase <= 1'b0;
        end else begin
            rise_phase <= count < HIGH;
            count <= (count == LAST) ? {W{1'b0}} : count + 1'b1;
        end
    end
    always @(negedge clk or negedge arst_n) begin
        if (!arst_n) fall_phase <= 1'b0;
        else fall_phase <= rise_phase;
    end

    assign clk_out = (MUTATION == 5) ? rise_phase : (rise_phase | fall_phase);
endmodule
