// Negative example: a binary counter is synchronised bit by bit.
// Several bits change at once, so the b domain can see a count that was never there.
module cdc_multibit (
    input  wire a_clk, b_clk,
    input  wire a_step,
    output wire [2:0] b_count
);
    reg [2:0] a_count;
    reg [2:0] b_meta, b_stable;
    always @(posedge a_clk) if (a_step) a_count <= a_count + 3'd1;
    always @(posedge b_clk) begin
        b_meta <= a_count;
        b_stable <= b_meta;
    end
    assign b_count = b_stable;
endmodule
