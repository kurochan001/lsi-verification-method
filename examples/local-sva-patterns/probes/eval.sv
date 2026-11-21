// One small trace per case; the property under test prints the cycle of each failure.
// Columns of a row: a, b, c, v[3:0], w[3:0].
module eval;
  bit clk = 0;
  int cyc = 0;
  logic a, b, c;
  logic [3:0] v, w;
  logic [10:0] rom [0:23];
  always #5 clk = ~clk;
  initial begin
    for (int i = 0; i < 24; i++) rom[i] = '0;
`ifdef RANGE_CONSEQUENT        // b answers the first a after 3 cycles, the second a too late
    rom[2][10] = 1; rom[5][9] = 1; rom[8][10] = 1; rom[13][9] = 1;
`elsif LOCALVAR_FIXED          // w equals the captured v after 2 cycles, then does not
    rom[2] = {3'b100, 4'd5, 4'd0}; rom[4][3:0] = 4'd5; rom[6] = {3'b100, 4'd7, 4'd0}; rom[8][3:0] = 4'd3;
`elsif GOTO_FIRST_CYCLE        // c comes in the first cycle after a; the next a is legal
    rom[2][10] = 1; rom[3][8] = 1; rom[6][10] = 1; rom[8][8] = 1;
`else                          // a with v=1, c with w=1; a with v=2, c with w=3 (wrong)
    rom[2] = {3'b100, 4'd1, 4'd0}; rom[5] = {3'b001, 4'd0, 4'd1};
    rom[7] = {3'b100, 4'd2, 4'd0}; rom[10] = {3'b001, 4'd0, 4'd3};
`endif
  end
  assign {a, b, c, v, w} = rom[cyc];
  always @(posedge clk) begin
    cyc <= cyc + 1;
    if (cyc == 20) begin
      $display("PROBE_DONE");
      $finish;
    end
  end
`ifdef RANGE_CONSEQUENT
  ap: assert property (@(posedge clk) a |-> ##[1:3] b) else $display("PROBE_FAIL %0d", cyc);
`elsif LOCALVAR_FIXED
  property p;
    logic [3:0] x;
    @(posedge clk) (a, x = v) |-> ##2 (w == x);
  endproperty
  ap: assert property (p) else $display("PROBE_FAIL %0d", cyc);
`elsif GOTO_FIRST_CYCLE
  ap: assert property (@(posedge clk) a |=> (!a) throughout c[->1]) else $display("PROBE_FAIL %0d", cyc);
`elsif RANGE_ANTECEDENT
  ap: assert property (@(posedge clk) a ##[1:5] c |-> w == 4'd1) else $display("PROBE_FAIL %0d", cyc);
`elsif UNBOUNDED_CONSEQUENT
  ap: assert property (@(posedge clk) a |=> (!c)[*0:$] ##1 (c && w == 4'd1)) else $display("PROBE_FAIL %0d", cyc);
`elsif LOCALVAR_GOTO
  property p;
    logic [3:0] x;
    @(posedge clk) (a, x = v) ##1 c[->1] |-> w == x;
  endproperty
  ap: assert property (p) else $display("PROBE_FAIL %0d", cyc);
`endif
  wire unused = b;
endmodule
