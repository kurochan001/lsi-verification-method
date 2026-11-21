module probe(input logic clk, clk_b, a, b, input logic [3:0] v, w);
  property p;
    logic [3:0] x;
    @(posedge clk) (a, x = v) |-> ##2 (w == x);
  endproperty
  ap: assert property (p);
endmodule
