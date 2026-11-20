// One-time-programmable fuses, as a behavioural model: a programmed bit never returns to 0.
// There is no functional reset. `blank` stands for the state of an unprogrammed device and is
// driven by the test bench only.
module fuse_bank #(parameter WIDTH = 8) (
    input  wire             clk,
    input  wire             blank,
    input  wire             prog,
    input  wire [WIDTH-1:0] d,
    output reg  [WIDTH-1:0] q
);
    always @(posedge clk) begin
        if (blank) q <= {WIDTH{1'b0}};
        else if (prog) q <= q | d;
    end
endmodule
