// fault_xor is a verification hook, applied to stored state after a normal update.
// Tie it to zero when using the ordinary register behavior.
module plain_register #(parameter WIDTH=32)(
    input wire clk,rst_n,write_en,
    input wire [WIDTH-1:0] write_data,fault_xor,
    output reg [WIDTH-1:0] q
);
    always @(posedge clk) begin
        if (!rst_n) q <= {WIDTH{1'b0}};
        else q <= (write_en ? write_data : q) ^ fault_xor;
    end
endmodule
