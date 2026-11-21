// Four-entry queue of tagged items with a fixed processing delay before each head is offered.
// An identifier that is still inside the queue is refused at the input.
module tagged_queue #(
  parameter DATA_W = 8,
  parameter LAT = 1,
  parameter MUTATION = 0
) (
  input  logic              clk,
  input  logic              rst_n,
  input  logic              in_valid,
  output logic              in_ready,
  input  logic [1:0]        in_id,
  input  logic [DATA_W-1:0] in_data,
  output logic              out_valid,
  input  logic              out_ready,
  output logic [1:0]        out_id,
  output logic [DATA_W-1:0] out_data
);
  logic [DATA_W+1:0] mem [0:3];
  logic [3:0]        wr_sel;
  logic [1:0]        rd_ptr;
  logic [2:0]        count;
  logic [2:0]        wait_cnt;
  logic [3:0]        inflight;

  wire [2:0] lat   = LAT[2:0];
  wire       empty = count == 3'd0;
  wire       full  = count == 3'd4;
  wire       in_fire  = in_valid && in_ready;
  wire       out_fire = out_valid && out_ready;
  // A new head starts its delay when it enters an empty queue or when the old head leaves.
  wire       head_in   = in_fire && (empty || (out_fire && count == 3'd1));
  wire       head_next = out_fire && count > 3'd1;
  wire [1:0] wr_ptr = {wr_sel[3] | wr_sel[2], wr_sel[3] | wr_sel[1]};
  wire [1:0] rd_idx = (MUTATION == 5 && count == 3'd3) ? rd_ptr + 2'd1 : rd_ptr;

  assign in_ready  = !full && (MUTATION == 4 || !inflight[in_id]);
  assign out_valid = !empty && wait_cnt == 3'd0 && !(MUTATION == 1 && in_valid);
  assign {out_id, out_data} = mem[rd_idx];

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      wr_sel   <= 4'b0001;
      rd_ptr   <= 2'd0;
      count    <= 3'd0;
      wait_cnt <= 3'd0;
      inflight <= 4'd0;
    end else begin
      if (in_fire) begin
        mem[wr_ptr] <= {in_id, in_data};
        wr_sel <= (MUTATION == 2 && wr_sel[3]) ? 4'b0011 : {wr_sel[2:0], wr_sel[3]};
      end
      if (out_fire) rd_ptr <= rd_ptr + 2'd1;
      count <= count + {2'd0, in_fire} - {2'd0, out_fire};
      if (out_fire) inflight[out_id] <= 1'b0;
      if (in_fire) inflight[in_id] <= 1'b1;
      if (head_in)        wait_cnt <= (MUTATION == 7 && empty) ? lat + 3'd1 : lat;
      else if (head_next) wait_cnt <= (MUTATION == 3) ? lat + 3'd1 : lat;
      else if (wait_cnt != 3'd0) wait_cnt <= wait_cnt - 3'd1;
    end
  end
endmodule
