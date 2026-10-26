`timescale 1ns/1ps
module apb_irq_tb;
  parameter integer WAIT_CYCLES = 0;
  parameter integer MUTATION = 0;
  reg clk = 0, rst_n = 0, psel = 0, penable = 0, pwrite = 0;
  reg [7:0] paddr = 0;
  reg [31:0] pwdata = 0;
  reg [3:0] events = 0;
  wire pready, pslverr, irq;
  wire [31:0] prdata, config_value;
  wire [3:0] pending;
  reg [31:0] model_config = 0, expected_data;
  reg [3:0] model_pending = 0;
  integer elapsed = 0, checks = 0, fd, fields;
  integer vr, vs, ve, vw, va, vd_events;
  reg [31:0] vd;
  bit ready_expected, error_expected, accepted, invalid;
  bit previous_active = 0, must_hold = 0, previous_done = 0;
  bit old_write;
  reg [7:0] old_address;
  reg [31:0] old_data;
  reg [31:0] before_config;
  reg [3:0] before_pending;
  bit expected_irq, before_irq, recovering = 0;
  integer before_active_count, after_active_count;
  string vectors, wave, address_class;
  apb_irq #(.WAIT_CYCLES(WAIT_CYCLES), .MUTATION(MUTATION)) dut (
    clk, rst_n, psel, penable, pwrite, paddr, pwdata, events,
    pready, pslverr, prdata, config_value, pending, irq
  );
  always #5 clk = !clk;
  task fail(input string label);
    begin
      $display("CHECK_FAIL %s", label);
      $fatal(1, "cycle=%0d addr=%h config=%h expected=%h pending=%h expected=%h",
             checks, paddr, config_value, model_config, pending, model_pending);
    end
  endtask
  task cycle;
    begin
      @(negedge clk);
      rst_n = vr; psel = vs; penable = ve; pwrite = vw;
      paddr = va; pwdata = vd; events = vd_events;
      #1;
      accepted = 0; invalid = 0;
      if (rst_n) begin
        // Monitor the generated master's SETUP/ACCESS and stalled stability.
        if (must_hold && (!psel || !penable || paddr !== old_address ||
            pwrite !== old_write || (pwrite && pwdata !== old_data))) fail("APB_MASTER_STABILITY");
        if (psel && penable && !previous_active) fail("APB_MASTER_SETUP");
        if (previous_done && psel && penable) fail("APB_MASTER_BACK_TO_BACK");
        ready_expected = psel && penable && elapsed >= WAIT_CYCLES;
        accepted = ready_expected;
        invalid = (paddr != 0 && paddr != 4 && paddr != 8) || (pwrite && paddr == 4);
        error_expected = accepted && invalid;
        if (pready !== ready_expected) fail("APB_READY");
        if (pslverr !== error_expected) fail("APB_ERROR_RESPONSE");
        if (accepted && !pwrite) begin
          case (paddr)
            0: expected_data = model_config;
            4: expected_data = 32'h41504233;
            8: expected_data = {28'b0, model_pending};
            default: expected_data = 0;
          endcase
          if (prdata !== expected_data) fail("APB_READ_DATA");
        end
      end
      before_config = model_config; before_pending = model_pending;
      before_irq = 0;
      for (integer b = 0; b < 4; b = b + 1)
        if (before_config[b] && before_pending[b]) before_irq = 1;
      @(posedge clk);
      if (!rst_n) begin
        model_config = 0; model_pending = 0; elapsed = 0;
      end else begin
        if (accepted && pwrite && !invalid && paddr == 0) model_config = pwdata;
        // Per-bit reference, deliberately different from DUT's mask expression.
        for (integer b = 0; b < 4; b = b + 1) begin
          if (accepted && pwrite && paddr == 8 && pwdata[b]) model_pending[b] = 0;
          if (events[b]) model_pending[b] = 1;
        end
        if (psel && !penable) elapsed = 0;
        else if (psel && penable) elapsed = elapsed + 1;
      end
      #1;
      checks = checks + 1;
      if (config_value !== model_config) begin
        if (accepted && invalid && pwrite) fail("APB_ERROR_SIDE_EFFECT");
        else fail("APB_STATE");
      end
      if (pending !== model_pending) fail("APB_IRQ_PENDING");
      expected_irq = 0; before_active_count = 0; after_active_count = 0;
      for (integer b = 0; b < 4; b = b + 1) begin
        if (model_config[b] && model_pending[b]) begin
          expected_irq = 1; after_active_count = after_active_count + 1;
        end
        if (before_config[b] && before_pending[b]) before_active_count = before_active_count + 1;
      end
      if (irq !== expected_irq) begin
        if (rst_n && accepted && pwrite && paddr == 8 && !expected_irq && before_irq)
          fail("APB_IRQ_RELEASE");
        else fail("APB_IRQ_OUTPUT");
      end
      // Every observation follows the complete response/state/IRQ comparison.
      if (!rst_n) begin
        recovering = before_irq;
        if (before_irq) $display("COVER reset/active-irq");
      end else begin
        if (recovering && expected_irq && |events) begin
          $display("COVER reset/recovery"); recovering = 0;
        end
        if (previous_done && psel && !penable) $display("COVER bus/back-to-back");
        if (psel && !penable && |events) $display("COVER event/setup");
        if (psel && penable && !accepted && |events) $display("COVER event/wait");
        if (accepted && invalid && |events) $display("COVER event/error-response");
        if (accepted && pwrite && paddr == 8) begin
          for (integer b = 0; b < 4; b = b + 1) begin
            if (before_pending[b])
              $display("COVER cross/bit%0d/mask%0d/clear%0d/event%0d",
                       b, before_config[b], pwdata[b], events[b]);
          end
          if (before_irq && !expected_irq) $display("COVER sequence/clear-release");
          if (before_active_count > 1 && after_active_count == 1)
            $display("COVER multi/partial-clear");
          if (before_active_count == 1 && after_active_count == 0)
            $display("COVER multi/last-clear");
        end
        if (accepted && pwrite && paddr == 0) begin
          for (integer b = 0; b < 4; b = b + 1) begin
            if (before_pending[b] && !before_config[b] && model_config[b])
              $display("COVER sequence/unmask-pending");
            if (before_pending[b] && before_config[b] && !model_config[b])
              $display("COVER sequence/mask-pending");
            if (!before_config[b] && model_config[b] && events[b])
              $display("COVER simultaneous/enable-event");
            if (before_config[b] && !model_config[b] && events[b])
              $display("COVER simultaneous/disable-event");
          end
        end
      end
      previous_active = rst_n && psel;
      must_hold = rst_n && psel && (!penable || !accepted);
      previous_done = rst_n && accepted;
      old_address = paddr; old_write = pwrite; old_data = pwdata;
    end
  endtask
  initial begin
    if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "Missing VECTORS");
    if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, apb_irq_tb); end
    fd = $fopen(vectors, "r");
    if (!fd) $fatal(1, "Cannot open vectors");
    while (!$feof(fd)) begin
      fields = $fscanf(fd, "%d %d %d %d %h %h %h\n", vr, vs, ve, vw, va, vd, vd_events);
      if (fields != 7) fail("APB_VECTOR_FORMAT");
      cycle();
    end
    $fclose(fd);
    $display("RESULT PASS checks=%0d", checks);
    $finish;
  end
endmodule
