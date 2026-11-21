`timescale 1ns/1ns
// Simulation top for the trace harness: row r is clocked at time 5 + 20 * r.
module trace_tb;
  localparam LEN = 48;
  bit gclk = 0;
  int sel_arg;
  logic [2:0] sel;
  always #5 gclk = ~gclk;
  initial begin
    if (!$value$plusargs("SEL=%d", sel_arg)) $fatal(1, "SEL missing");
    sel = sel_arg[2:0];
    #(20 * LEN);
    $display("TRACE_DONE");
    $finish;
  end
  trace_harness #(.LEN(LEN)) u (.gclk(gclk), .sel(sel));
endmodule
