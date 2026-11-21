module probe(input logic clk, clk_b, a, b, input logic [3:0] v, w);
  always @(posedge clk) if (a) ap: assert ($past(b) || $stable(v) || w != 4'd0);
endmodule
