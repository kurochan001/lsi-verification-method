// Formal top for the queue: free inputs, with reset applied in the first step only.
module queue_formal #(parameter LAT = 1, parameter MUTATION = 0) (
  input logic       clk,
  input logic       in_valid,
  input logic [1:0] in_id,
  input logic [1:0] in_data,
  input logic       out_ready
);
  logic released = 1'b0;
  logic in_ready, out_valid;
  logic [1:0] out_id, out_data;
  always @(posedge clk) released <= 1'b1;
  tagged_queue #(.DATA_W(2), .LAT(LAT), .MUTATION(MUTATION)) u_queue (
    .clk(clk), .rst_n(released), .in_valid(in_valid), .in_ready(in_ready), .in_id(in_id),
    .in_data(in_data), .out_valid(out_valid), .out_ready(out_ready), .out_id(out_id),
    .out_data(out_data));
endmodule
