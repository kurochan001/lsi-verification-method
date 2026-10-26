`timescale 1ns/1ps
module apb_tb;
  parameter integer WAIT_CYCLES = 0;
  parameter integer MUTATION = 0;
  reg clk = 0, rst_n = 0, psel = 0, penable = 0, pwrite = 0;
  reg [7:0] paddr = 0;
  reg [31:0] pwdata = 0;
  reg [3:0] events = 0;
  wire pready, pslverr;
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
  string vectors, wave, address_class;
  apb_regs #(.WAIT_CYCLES(WAIT_CYCLES), .MUTATION(MUTATION)) dut (
    clk, rst_n, psel, penable, pwrite, paddr, pwdata, events,
    pready, pslverr, prdata, config_value, pending
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
      if (pending !== model_pending) fail("APB_W1C");
      // Credit only observations whose response and state checks passed.
      if (!rst_n) begin
        if (psel && penable) $display("COVER reset/access");
        else if (psel) $display("COVER reset/setup");
        else $display("COVER reset/idle");
      end else begin
        if (previous_done && psel && !penable) $display("COVER bus/back-to-back");
        if (psel && penable && !accepted) $display("COVER bus/wait");
        if (accepted) begin
          case (paddr)
            0: address_class = "config";
            4: address_class = "id";
            8: address_class = "pending";
            1: address_class = "unaligned";
            default: address_class = "unmapped";
          endcase
          if (pwrite) $display("COVER cross/%s/write", address_class);
          else $display("COVER cross/%s/read", address_class);
          if (pwrite && paddr == 0) begin
            if (pwdata == 0) $display("COVER data/zero");
            if (pwdata == 32'hffffffff) $display("COVER data/ones");
            if (pwdata == 32'h55555555) $display("COVER data/alternating");
          end
          if (pwrite && paddr == 8 && |(events & pwdata[3:0]))
            $display("COVER w1c/event-wins");
          if (pwrite && paddr == 8 && pwdata[3:0] == 0) $display("COVER w1c/zero");
          if (pwrite && paddr == 8 && pwdata[3:0] == 15 && events == 0)
            $display("COVER w1c/clear-all");
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
    if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, apb_tb); end
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
