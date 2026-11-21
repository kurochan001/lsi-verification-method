module probe(input logic clk, clk_b, a, b, input logic [3:0] v, w);
  ap: assert property (@(posedge clk) a |=> b);
endmodule
