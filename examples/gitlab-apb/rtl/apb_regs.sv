// Teaching peripheral: APB3 signal subset, synchronous active-low reset.
module apb_regs #(
  parameter integer WAIT_CYCLES = 0,
  parameter integer MUTATION = 0
) (
  input wire clk, rst_n, psel, penable, pwrite,
  input wire [7:0] paddr,
  input wire [31:0] pwdata,
  input wire [3:0] events,
  output wire pready, pslverr,
  output reg [31:0] prdata,
  output reg [31:0] config_value,
  output reg [3:0] pending
);
  integer remaining;
  wire access_done = psel && penable && pready;
  wire bad_address = paddr != 8'h00 && paddr != 8'h04 && paddr != 8'h08;
  wire bad_request = bad_address || (pwrite && paddr == 8'h04);
  wire clear_pending = access_done && pwrite && !bad_request && paddr == 8'h08;
  assign pready = psel && penable && remaining == 0;
  assign pslverr = access_done && bad_request;
  always @* begin
    prdata = 0;
    case (paddr)
      8'h00: prdata = config_value;
      8'h04: prdata = 32'h41504233;
      8'h08: prdata = {28'b0, pending};
      default: prdata = 0;
    endcase
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      remaining <= 0;
      config_value <= 0;
      pending <= 0;
    end else begin
      if (psel && !penable) remaining <= WAIT_CYCLES;
      else if (psel && penable && remaining > 0) remaining <= remaining - 1;
      if (access_done && pwrite && !bad_request && paddr == 0)
        config_value <= pwdata;
      // Intentional defects, enabled only for checker sensitivity tests.
      if (MUTATION == 1 && psel && !penable && pwrite && paddr == 0)
        config_value <= pwdata;
      if (MUTATION == 3 && access_done && pwrite && bad_request)
        config_value <= pwdata;
      if (MUTATION == 2 && clear_pending)
        pending <= (pending | events) & ~pwdata[3:0];
      else
        pending <= (pending & ~(clear_pending ? pwdata[3:0] : 4'b0)) | events;
    end
  end
endmodule
