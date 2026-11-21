// Requester (master) with retry on error responses and a response timeout.
// One command at a time: IDLE -> REQ (until accepted) -> WAIT (until response or timeout).
module req_master #(
  parameter RETRIES = 2,   // extra attempts after an error response (0..2)
  parameter TIMEOUT = 8,   // a response is taken up to TIMEOUT edges after acceptance (2..15)
  parameter MUTATION = 0
) (
  input wire clk,
  input wire rst_n,
  input wire cmd_valid,
  input wire cmd_write,
  input wire [7:0] cmd_addr,
  input wire [7:0] cmd_wdata,
  output wire cmd_ready,
  output wire req_valid,
  output wire req_write,
  output wire [7:0] req_addr,
  output wire [7:0] req_wdata,
  input wire req_ready,
  input wire rsp_valid,
  input wire rsp_err,
  input wire [7:0] rsp_rdata,
  output reg done_valid,
  output reg done_err,
  output reg done_timeout,
  output reg [7:0] done_rdata,
  output reg [1:0] done_tries
);
  localparam [1:0] IDLE = 2'd0, REQ = 2'd1, WAIT = 2'd2;
  localparam [1:0] MAX_RETRY = RETRIES[1:0] + ((MUTATION == 3) ? 2'd1 : 2'd0);
  localparam [3:0] LAST_EDGE = TIMEOUT[3:0] - ((MUTATION == 4) ? 4'd2 : 4'd1);

  reg [1:0] state;
  reg write;
  reg [7:0] addr, wdata;
  reg [1:0] retries;   // error responses already answered with a retry
  reg [3:0] timer;     // edges spent in WAIT without a response
  reg [1:0] stalled;   // saturating count of unaccepted REQ edges (used by mutation 1 only)

  wire retried = retries != 2'd0;
  wire take_idle = MUTATION == 8 && state == IDLE && rsp_valid;
  wire take_early = MUTATION == 5 && state == REQ && rsp_valid;
  wire take = (state == WAIT && rsp_valid) || take_early;

  assign cmd_ready = state == IDLE;
  assign req_valid = state == REQ;
  assign req_write = write;
  assign req_addr = addr ^ ((MUTATION == 1 && stalled == 2'd2) ? 8'h01 : 8'h00);
  assign req_wdata = wdata ^ ((MUTATION == 7 && retried) ? 8'h01 : 8'h00);

  always @(posedge clk) begin
    done_valid <= 1'b0;
    if (!rst_n) begin
      state <= IDLE;
      retries <= 2'd0;
      timer <= 4'd0;
      stalled <= 2'd0;
      done_err <= 1'b0;
      done_timeout <= 1'b0;
      done_rdata <= 8'h00;
      done_tries <= 2'd0;
    end else begin
      if (state == IDLE && cmd_valid) begin
        write <= cmd_write;
        addr <= cmd_addr;
        wdata <= cmd_wdata;
        retries <= 2'd0;
        stalled <= 2'd0;
        state <= REQ;
      end
      if (state == REQ) begin
        if (req_ready) begin
          timer <= 4'd0;
          stalled <= 2'd0;
          state <= WAIT;
        end else if (stalled != 2'd2) begin
          stalled <= stalled + 2'd1;
        end
      end
      if (take) begin
        if (rsp_err && retries != MAX_RETRY && MUTATION != 2) begin
          retries <= retries + 2'd1;
          state <= REQ;
        end else begin
          done_valid <= 1'b1;
          done_err <= rsp_err;
          done_timeout <= 1'b0;
          done_rdata <= write ? 8'h00 : ((MUTATION == 6) ? addr : rsp_rdata);
          done_tries <= retries + 2'd1;
          state <= IDLE;
        end
      end else if (state == WAIT) begin
        if (timer == LAST_EDGE && MUTATION != 9) begin
          done_valid <= 1'b1;
          done_err <= 1'b1;
          done_timeout <= 1'b1;
          done_rdata <= 8'h00;
          done_tries <= retries + 2'd1;
          state <= IDLE;
        end else if (timer != 4'd15) begin
          timer <= timer + 4'd1;
        end
      end
      if (take_idle) begin
        done_valid <= 1'b1;
        done_err <= rsp_err;
        done_timeout <= 1'b0;
        done_rdata <= rsp_rdata;
      end
    end
  end
endmodule
