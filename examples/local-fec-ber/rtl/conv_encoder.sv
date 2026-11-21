// Rate-1/2 convolutional encoder, constraint length 3, generators 7 and 5 (octal).
// One information bit in, one 2-bit symbol out in the same cycle: out_sym = {c0, c1},
//   c0 = u[n] ^ u[n-1] ^ u[n-2]      c1 = u[n] ^ u[n-2]
// The state advances on in_valid. A synchronous reset returns it to zero.
// MUTATION 1: c1 uses u[n-1] instead of u[n-2].
module conv_encoder #(
    parameter MUTATION = 0
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       in_valid,
    input  wire       in_bit,
    output wire [1:0] out_sym
);
    reg [1:0] state;   // {u[n-1], u[n-2]}

    assign out_sym = {in_bit ^ state[1] ^ state[0],
                      MUTATION == 1 ? in_bit ^ state[1] : in_bit ^ state[0]};

    always @(posedge clk) begin
        if (!rst_n) state <= 2'b00;
        else if (in_valid) state <= {in_bit, state[1]};
    end
endmodule
