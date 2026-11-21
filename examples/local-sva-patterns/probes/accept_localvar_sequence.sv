module probe(input logic clk, clk_b, a, b, input logic [3:0] v, w);
  property p;
    logic [3:0] x;
    @(posedge clk) (a, x = v) |=> (!(a && v == x)) throughout (b && w == x)[->1];
  endproperty
  ap: assert property (p);
endmodule
