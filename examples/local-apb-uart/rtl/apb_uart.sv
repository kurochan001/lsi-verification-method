// Teaching APB3 signal subset + existing UART + sticky event interrupts.
module apb_uart #(
  parameter integer WAIT_CYCLES = 0,
  parameter integer PARITY = 0,
  parameter integer DIVISOR = 8,
  parameter integer MUTATION = 0
) (
  input wire clk, rst_n, psel, penable, pwrite,
  input wire [7:0] paddr,
  input wire [31:0] pwdata,
  input wire rxd,
  output wire pready, pslverr,
  output reg [31:0] prdata,
  output wire txd, irq,
  output reg [3:0] mask, pending,
  output reg [7:0] rx_snapshot,
  output reg rx_available, saved_pe, saved_fe,
  output wire tx_ready
);
  integer remaining;
  wire rx_valid, pe, fe;
  wire [7:0] rx_data;
  reg was_busy;
  wire access_done = psel && penable && pready;
  reg bad_request;
  always @* begin
    case (paddr)
      8'h00, 8'h10: bad_request = 0;
      8'h04, 8'h14: bad_request = pwrite;
      8'h08: bad_request = !pwrite || !tx_ready;
      8'h0c: bad_request = pwrite || !rx_available;
      default: bad_request = 1;
    endcase
  end
  assign pready = rst_n && psel && penable && remaining == 0;
  assign pslverr = access_done && bad_request;
  wire write_tx = access_done && !bad_request && pwrite && paddr == 8'h08;
  wire clear_pending = access_done && !bad_request && pwrite && paddr == 8'h10;
  wire read_rx = access_done && !bad_request && !pwrite && paddr == 8'h0c;
  wire [3:0] events = {rx_valid && fe, rx_valid && pe, rx_valid, was_busy && tx_ready};
  wire [3:0] delivered = MUTATION == 1 ? events & mask : events;
  assign irq = MUTATION == 2 ? |pending : |(pending & mask);
  wire [7:0] transmit_data = MUTATION == 4 ? pwdata[7:0] ^ 8'h01 : pwdata[7:0];
  uart #(.DIVISOR(DIVISOR), .PARITY(PARITY), .MUTATION(0)) serial (
    clk, rst_n, write_tx, transmit_data, tx_ready, txd, rxd,
    rx_valid, rx_data, pe, fe
  );
  always @* begin
    prdata = 0;
    if (!bad_request) begin
      case (paddr)
        8'h00: prdata = {28'b0, mask};
        8'h04: prdata = {28'b0, saved_fe, saved_pe, rx_available, tx_ready};
        8'h0c: prdata = {24'b0, rx_snapshot};
        8'h10: prdata = {28'b0, pending};
        8'h14: prdata = 32'h55415254;
        default: prdata = 0;
      endcase
    end
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      remaining <= 0; mask <= 0; pending <= 0; was_busy <= 0;
      rx_snapshot <= 0; rx_available <= 0; saved_pe <= 0; saved_fe <= 0;
    end else begin
      if (psel && !penable) remaining <= WAIT_CYCLES;
      else if (psel && penable && remaining > 0) remaining <= remaining - 1;
      was_busy <= !tx_ready;
      if (access_done && !bad_request && pwrite && paddr == 0) mask <= pwdata[3:0];
      if (MUTATION == 3 && clear_pending)
        pending <= (pending | delivered) & ~pwdata[3:0];
      else pending <= (pending & ~(clear_pending ? pwdata[3:0] : 4'b0)) | delivered;
      if (read_rx) rx_available <= 0;
      // A simultaneous new receive wins over consuming the old snapshot.
      if (rx_valid) begin
        rx_available <= 1;
        rx_snapshot <= MUTATION == 5 ? rx_data ^ 8'h01 : rx_data;
        saved_pe <= pe; saved_fe <= fe;
      end
    end
  end
endmodule
