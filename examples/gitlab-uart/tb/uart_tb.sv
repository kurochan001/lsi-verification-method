`timescale 1ns/1ps
module uart_tb;
  parameter integer DIVISOR = 8;
  parameter integer PARITY = 0;
  parameter integer MUTATION = 0;
  localparam integer BIT_NS = DIVISOR * 10;
  reg clk = 0, rst_n = 0, tx_start = 0, rxd = 1;
  reg [7:0] tx_data = 0;
  wire tx_ready, txd, rx_valid, parity_error, framing_error;
  wire [7:0] rx_data;
  bit expect_rx = 0, expected_pe, expected_fe, rx_active = 0, overlap_seen = 0;
  bit previous_valid = 0, recovering = 0;
  reg [7:0] expected_rx, vtx, vrx;
  integer clocks = 0, checks = 0, tx_completed = 0, rx_completed = 0;
  integer resets = 0, false_starts = 0, fd, fields, mode, busy, gap, phase;
  string vectors, wave;
  uart #(.DIVISOR(DIVISOR), .PARITY(PARITY), .MUTATION(MUTATION)) dut (
    clk, rst_n, tx_start, tx_data, tx_ready, txd, rxd, rx_valid, rx_data, parity_error, framing_error
  );
  always #5 clk = !clk;
  task fail(input string label);
    begin
      $display("CHECK_FAIL %s", label);
      $fatal(1, "command=%0d clock=%0d txd=%b rx_valid=%b rx_data=%h expected=%h pe=%b fe=%b",
             checks, clocks, txd, rx_valid, rx_data, expected_rx, parity_error, framing_error);
    end
  endtask
  // Observe actual DUT receive pulses independently of the serial driver.
  always @(posedge clk) begin
    #1; clocks = clocks + 1;
    if (!rst_n) begin
      if (tx_ready !== 1'b1 || txd !== 1'b1 || rx_valid !== 1'b0 ||
          rx_data !== 8'b0 || parity_error !== 1'b0 || framing_error !== 1'b0) fail("UART_RESET");
      previous_valid = 0;
    end else begin
      if ((^{tx_ready, txd, rx_valid, parity_error, framing_error}) === 1'bx) fail("UART_UNKNOWN");
      if (!rx_valid && (parity_error || framing_error)) fail("UART_RX_FLAG_VALID");
      if (!tx_ready && rx_active) overlap_seen = 1;
      if (rx_valid) begin
        if (previous_valid) fail("UART_RX_PULSE");
        if (!expect_rx) fail("UART_RX_UNEXPECTED");
        if (rx_data !== expected_rx) fail("UART_RX_DATA");
        if (parity_error !== expected_pe) fail("UART_RX_PARITY");
        if (framing_error !== expected_fe) fail("UART_RX_FRAMING");
        expect_rx = 0; rx_completed = rx_completed + 1;
      end
      previous_valid = rx_valid;
    end
  end
  function automatic bit parity_for(input reg [7:0] value);
    bit result;
    begin
      result = PARITY == 2;
      for (integer i = 0; i < 8; i = i + 1) if (value[i]) result = !result;
      parity_for = result;
    end
  endfunction
  function automatic bit frame_bit(input reg [7:0] value, input integer index);
    begin
      if (index == 0) frame_bit = 0;
      else if (index <= 8) frame_bit = value[index - 1];
      else if (index == 9 && PARITY != 0) frame_bit = parity_for(value);
      else frame_bit = 1;
    end
  endfunction
  task check_tx(input reg [7:0] value, input bit inject_busy, input integer bits_to_check);
    begin
      @(negedge clk);
      if (!tx_ready) fail("UART_TX_NOT_READY");
      tx_start = 1; tx_data = value;
      @(posedge clk); #2; tx_start = 0;
      for (integer b = 0; b < bits_to_check; b = b + 1) begin
        for (integer tick = 0; tick < DIVISOR; tick = tick + 1) begin
          if (b != 0 || tick != 0) begin @(posedge clk); #2; end
          if (tx_ready !== 0) fail("UART_TX_EARLY_READY");
          if (txd !== frame_bit(value, b)) begin
            if (b >= 1 && b <= 8) fail("UART_TX_DATA");
            else if (b == 9 && PARITY != 0) fail("UART_TX_PARITY");
            else fail("UART_TX_FRAMING");
          end
          if (inject_busy && b == 3 && tick == 1) begin tx_start = 1; tx_data = ~value; end
          if (inject_busy && b == 3 && tick == 2) tx_start = 0;
        end
      end
      if (bits_to_check > 4) begin
        @(posedge clk); #2;
        if (tx_ready !== 1 || txd !== 1) fail("UART_TX_COMPLETION");
        tx_completed = tx_completed + 1;
      end
    end
  endtask
  task drive_rx(input reg [7:0] value, input bit flip_parity, input bit bad_stop, input integer offset);
    begin
      if (expect_rx) fail("UART_RX_PENDING");
      expected_rx = value; expected_pe = PARITY != 0 && flip_parity; expected_fe = bad_stop;
      expect_rx = 1;
      @(negedge clk); #(offset == 0 ? 1 : 7);
      rx_active = 1; rxd = 0; #(BIT_NS);
      for (integer b = 0; b < 8; b = b + 1) begin rxd = value[b]; #(BIT_NS); end
      if (PARITY != 0) begin rxd = parity_for(value) ^ flip_parity; #(BIT_NS); end
      rxd = !bad_stop; #(BIT_NS);
      rxd = 1; rx_active = 0;
      if (bad_stop) #(2 * BIT_NS);
      #2;
      if (expect_rx) fail("UART_RX_MISSING");
    end
  endtask
  task false_start;
    begin
      @(negedge clk); #1;
      rxd = 0; #(BIT_NS / 4); rxd = 1; #(2 * BIT_NS);
      false_starts = false_starts + 1;
    end
  endtask
  task reset_active(input reg [7:0] value);
    begin
      fork
        check_tx(value, 0, 4);
        begin
          @(negedge clk); #1;
          rxd = 0; #(BIT_NS);
          for (integer b = 0; b < 3; b = b + 1) begin rxd = value[b]; #(BIT_NS); end
        end
      join
      @(negedge clk); rst_n = 0; rxd = 1; tx_start = 0;
      repeat (2) @(negedge clk);
      rst_n = 1;
      repeat (2 * DIVISOR) @(negedge clk);
      resets = resets + 1; recovering = 1;
    end
  endtask
  task data_cover(input reg [7:0] value, input string direction);
    begin
      if (value == 8'h00) $display("COVER %s/data-zero", direction);
      if (value == 8'hff) $display("COVER %s/data-ones", direction);
      if (value == 8'h55) $display("COVER %s/data-alternating", direction);
      if (value == 8'h01) $display("COVER %s/data-lsb", direction);
      if (value == 8'h80) $display("COVER %s/data-msb", direction);
    end
  endtask
  initial begin
    if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "Missing VECTORS");
    if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, uart_tb); end
    repeat (4) @(negedge clk);
    rst_n = 1;
    fd = $fopen(vectors, "r");
    if (!fd) $fatal(1, "Cannot open vectors");
    while (!$feof(fd)) begin
      fields = $fscanf(fd, "%d %h %h %d %d %d\n", mode, vtx, vrx, busy, gap, phase);
      if (fields != 6) fail("UART_VECTOR_FORMAT");
      overlap_seen = 0;
      case (mode)
        0, 1, 2: begin
          fork
            check_tx(vtx, busy != 0, PARITY == 0 ? 10 : 11);
            drive_rx(vrx, mode == 1, mode == 2, phase);
          join
          if (expect_rx) fail("UART_RX_MISSING");
          data_cover(vtx, "tx"); data_cover(vrx, "rx");
          $display("COVER tx/normal");
          if (mode == 0) $display("COVER rx/normal");
          if (mode == 1 && PARITY != 0) $display("COVER rx/parity-error");
          if (mode == 2) $display("COVER rx/framing-error");
          if (busy != 0) $display("COVER tx/busy-ignore");
          if (overlap_seen) $display("COVER duplex/simultaneous");
          if (phase == 0) $display("COVER phase/early");
          else $display("COVER phase/late");
          if (recovering) begin $display("COVER reset/recovery"); recovering = 0; end
        end
        3: begin false_start(); $display("COVER rx/false-start"); end
        4: begin reset_active(vtx); $display("COVER reset/active"); end
        default: fail("UART_VECTOR_MODE");
      endcase
      repeat (gap * DIVISOR + 2) @(negedge clk);
      if (!tx_ready || txd !== 1 || rxd !== 1 || expect_rx) fail("UART_IDLE");
      checks = checks + 1;
    end
    $fclose(fd);
    repeat (2 * DIVISOR) @(negedge clk);
    $display("COVER idle/line-high");
    $display("METRICS tx_completed=%0d rx_completed=%0d resets=%0d false_starts=%0d clocks=%0d",
             tx_completed, rx_completed, resets, false_starts, clocks);
    $display("RESULT PASS checks=%0d", checks);
    $finish;
  end
endmodule
