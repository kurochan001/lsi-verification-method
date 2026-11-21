// Pattern 5a: a payload accepted with valid appears exactly LAT cycles later with q_valid.
// The assertion form captures the payload in a property local variable.
`ifndef FORMAL
module pat_pipe_sva #(parameter W = 8, parameter LAT = 2) (
  input logic clk, rst_n, valid, q_valid, input logic [W-1:0] data, q_data);
  property p_pipe;
    logic [W-1:0] x;
    @(posedge clk) disable iff (!rst_n) (valid, x = data) |-> ##LAT (q_valid && q_data == x);
  endproperty
  ap: assert property (p_pipe) else $display("PAT_FAIL %m %0t", $time);
  cp: cover property (@(posedge clk) rst_n && valid) $display("PAT_HIT %m %0t", $time);
endmodule
`endif

module pat_pipe_aux #(parameter W = 8, parameter LAT = 2) (
  input logic clk, rst_n, valid, q_valid, input logic [W-1:0] data, q_data);
  logic [LAT-1:0] due;
  logic [W-1:0]   kept [0:LAT-1];
  always @(posedge clk) begin
    if (!rst_n) due <= '0;
    else begin
      due[0] <= valid;
      kept[0] <= data;
      for (int i = 1; i < LAT; i++) begin
        due[i] <= due[i-1];
        kept[i] <= kept[i-1];
      end
    end
  end
  wire hit = valid;
  wire bad = due[LAT-1] && !(q_valid && q_data == kept[LAT-1]);
  `include "pat_report.svh"
endmodule
