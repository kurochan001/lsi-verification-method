module probe(input logic clk, clk_b, a, b, input logic [3:0] v, w);
  logic inner;
  always @(posedge clk) inner <= a ^ b ^ clk_b ^ (v == w);
endmodule
module probe_checker(input logic clk, inner);
  always @(posedge clk) ap: assert (inner || !inner);
endmodule
bind probe probe_checker u_checker (.clk(clk), .inner(inner));
