// Single-clock, two-state harness for the existing synchronous FIFO.
// Only the first sampled edge is constrained to reset in normal tasks.
module fifo_formal #(
  parameter integer DEPTH = 3,
  parameter integer WIDTH = 8,
  parameter integer MUTATION = 0,
  parameter integer CHECK_DATA = 0,
  parameter integer LOCK_RESET = 0
) (
  input wire clk, rst_n, wr_en, rd_en,
  input wire [WIDTH-1:0] wr_data
);
  localparam integer CW = $clog2(DEPTH + 1);
  wire [WIDTH-1:0] rd_data;
  wire rd_valid, full, empty;
  wire [CW-1:0] count;
  sync_fifo #(.DEPTH(DEPTH), .WIDTH(WIDTH), .MUTATION(MUTATION)) dut (
    clk, rst_n, wr_en, rd_en, wr_data, rd_data, rd_valid, full, empty, count
  );

  reg past_valid = 0;
  reg [CW-1:0] reference_count;
  reg [WIDTH-1:0] queue [0:DEPTH-1];
  reg [WIDTH-1:0] reference_output;
  wire push = rst_n && wr_en && reference_count < DEPTH;
  wire pop = rst_n && rd_en && reference_count > 0;
  integer i;
  // Saturating history, used only for cover goals, not as DUT assumptions.
  integer writes_since_reset = 0;
  reg recovery_pending = 0;

  always @(posedge clk) begin
    past_valid <= 1;
    if (!past_valid) as_initial_reset: assume (!rst_n);
    if (LOCK_RESET) as_lock_reset: assume (!rst_n);

    if (!rst_n) begin
      reference_count <= 0;
      reference_output <= 0;
      writes_since_reset <= 0;
      if (past_valid && reference_count > 0) recovery_pending <= 1;
    end else begin
      case ({push, pop})
        2'b10: reference_count <= reference_count + 1'b1;
        2'b01: reference_count <= reference_count - 1'b1;
        default: reference_count <= reference_count;
      endcase
      if (pop) begin
        reference_output <= queue[0];
        for (i = 0; i < DEPTH - 1; i = i + 1) queue[i] <= queue[i+1];
      end
      if (push) begin
        // Linear reference queue: a simultaneous pop makes room at the tail.
        queue[reference_count - (pop ? 1 : 0)] <= wr_data;
        if (writes_since_reset < 2 * DEPTH)
          writes_since_reset <= writes_since_reset + 1;
      end
      if (recovery_pending && pop) recovery_pending <= 0;
    end

    if (past_valid) begin
      ap_count: assert (count == reference_count);
      ap_bounds: assert (count <= DEPTH);
      ap_flags: assert (empty == (reference_count == 0) && full == (reference_count == DEPTH));
      ap_read_valid: assert (rd_valid == $past(pop));
      if (!$past(rst_n))
        ap_reset: assert (count == 0 && rd_data == 0 && !rd_valid);
      if ($past(rst_n && !pop))
        ap_hold: assert (rd_data == $past(rd_data));
      if (CHECK_DATA) ap_data: assert (rd_data == reference_output);

      cp_empty: cover (rst_n && reference_count == 0);
      cp_full: cover (rst_n && reference_count == DEPTH);
      cp_simultaneous: cover (rst_n && wr_en && rd_en);
      cp_reset_pending: cover (!rst_n && reference_count > 0);
      cp_recovery: cover (rst_n && recovery_pending && pop);
      cp_wrap: cover (rst_n && writes_since_reset == 2 * DEPTH && pop);
    end
  end
endmodule
