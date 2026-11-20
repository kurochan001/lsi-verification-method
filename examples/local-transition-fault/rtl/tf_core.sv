// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Four scan flops around a small next-state function. Six named nodes pass through a TFSITE cell,
// which synthesis keeps: the simulation model of that cell can hold the node or make it slow.
//   chain: scan_in -> q[0] -> q[1] -> q[2] -> q[3] -> scan_out
// There is no reset: the state is loaded through the chain.
// MUTATION 3 leaves q[2] out of the chain. MUTATION 4 turns the AND of n2 into an OR.
module tf_core #(parameter MUTATION = 0) (
    input  wire clk, scan_enable, scan_in, x,
    output wire scan_out
);
    reg [3:0] q;
    wire n0, n1, n2, n3, n4, n5;
    wire n0_raw = q[0] ^ q[1];
    wire n1_raw = q[2] | x;
    wire n2_raw = MUTATION == 4 ? n0 | n1 : n0 & n1;
    wire n3_raw = ~(q[1] & q[3]);
    wire n4_raw = n2 ^ q[3];
    wire n5_raw = ~q[0] & ~q[1] & q[3];
    TFSITE site_n0(.A(n0_raw), .Y(n0));
    TFSITE site_n1(.A(n1_raw), .Y(n1));
    TFSITE site_n2(.A(n2_raw), .Y(n2));
    TFSITE site_n3(.A(n3_raw), .Y(n3));
    TFSITE site_n4(.A(n4_raw), .Y(n4));
    TFSITE site_n5(.A(n5_raw), .Y(n5));
    wire [3:0] next = {n2 | n5, n4, n0, n3};
    wire [3:0] shifted = {MUTATION == 3 ? q[1] : q[2], q[1], q[0], scan_in};
    always @(posedge clk) q <= scan_enable ? shifted : next;
    assign scan_out = q[3];
endmodule
