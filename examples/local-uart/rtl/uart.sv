`timescale 1ns/1ps
// Teaching UART: 8 data bits, one stop bit, PARITY 0=none, 1=even, 2=odd.
module uart #(
  parameter integer DIVISOR = 8,
  parameter integer PARITY = 0,
  parameter integer MUTATION = 0
) (
  input wire clk, rst_n,
  input wire tx_start,
  input wire [7:0] tx_data,
  output wire tx_ready, txd,
  input wire rxd,
  output reg rx_valid,
  output reg [7:0] rx_data,
  output reg parity_error, framing_error
);
  reg [10:0] tx_shift;
  integer tx_ticks, tx_left;
  wire [7:0] payload = MUTATION == 1 ? tx_data ^ 8'h01 : tx_data;
  wire parity_bit = (^tx_data) ^ (PARITY == 2);
  assign tx_ready = tx_left == 0;
  assign txd = tx_ready ? 1'b1 : tx_shift[0];
  always @(posedge clk) begin
    if (!rst_n) begin tx_shift <= 11'h7ff; tx_ticks <= 0; tx_left <= 0; end
    else if (tx_ready) begin
      if (tx_start) begin
        tx_shift <= PARITY == 0 ? {2'b11, payload, 1'b0} : {1'b1, parity_bit, payload, 1'b0};
        tx_left <= PARITY == 0 ? 10 : 11;
        tx_ticks <= DIVISOR - 1;
      end
    end else if (tx_ticks == 0) begin
      tx_shift <= {1'b1, tx_shift[10:1]};
      tx_left <= tx_left - 1;
      tx_ticks <= DIVISOR - 1;
    end else tx_ticks <= tx_ticks - 1;
  end

  reg rx_meta, rx_sync;
  reg [7:0] rx_shift;
  reg saved_parity_error;
  integer state, rx_ticks, bit_index;
  localparam IDLE=0, START=1, DATA=2, PARITY_BIT=3, STOP=4, WAIT_HIGH=5;
  always @(posedge clk) begin
    if (!rst_n) begin rx_meta <= 1; rx_sync <= 1; end
    else begin rx_meta <= rxd; rx_sync <= rx_meta; end
  end
  always @(posedge clk) begin
    if (!rst_n) begin
      state <= IDLE; rx_ticks <= 0; bit_index <= 0; rx_shift <= 0;
      rx_valid <= 0; rx_data <= 0; parity_error <= 0; framing_error <= 0; saved_parity_error <= 0;
    end else begin
      rx_valid <= 0; parity_error <= 0; framing_error <= 0;
      case (state)
        IDLE: if (!rx_sync) begin state <= START; rx_ticks <= DIVISOR / 2 - 1; end
        START: begin
          if (rx_ticks != 0) rx_ticks <= rx_ticks - 1;
          else if (rx_sync) state <= IDLE;
          else begin
            state <= DATA; rx_ticks <= DIVISOR - 1; bit_index <= 0;
            rx_shift <= 0; saved_parity_error <= 0;
          end
        end
        DATA: begin
          if (rx_ticks != 0) rx_ticks <= rx_ticks - 1;
          else begin
            rx_shift[bit_index] <= rx_sync; rx_ticks <= DIVISOR - 1;
            if (bit_index == 7) state <= PARITY == 0 ? STOP : PARITY_BIT;
            else bit_index <= bit_index + 1;
          end
        end
        PARITY_BIT: begin
          if (rx_ticks != 0) rx_ticks <= rx_ticks - 1;
          else begin
            saved_parity_error <= rx_sync != ((^rx_shift) ^ (PARITY == 2));
            state <= STOP; rx_ticks <= DIVISOR - 1;
          end
        end
        STOP: begin
          if (rx_ticks != 0) rx_ticks <= rx_ticks - 1;
          else begin
            rx_data <= MUTATION == 2 ? rx_shift ^ 8'h01 : rx_shift;
            rx_valid <= 1;
            parity_error <= PARITY == 0 || MUTATION == 4 ? 1'b0 : saved_parity_error;
            framing_error <= MUTATION == 3 ? 1'b0 : !rx_sync;
            state <= WAIT_HIGH;
          end
        end
        WAIT_HIGH: if (rx_sync) state <= IDLE;
        default: state <= IDLE;
      endcase
    end
  end
endmodule
