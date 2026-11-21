`timescale 1ns/1ps
`include "uvm_macros.svh"
module top;
  import uvm_pkg::*;
  import rx_pkg::*;
  localparam int VARIANTS = 10;
  bit clk = 0;
  always #5 clk = !clk;
  rx_if bus(clk);
  int mutation, sva_off;
  wire [VARIANTS-1:0] cmd_ready, req_valid, req_write, done_valid, done_err, done_timeout;
  wire [7:0] req_addr[VARIANTS], req_wdata[VARIANTS], done_rdata[VARIANTS];
  wire [1:0] done_tries[VARIANTS];
  for (genvar m = 0; m < VARIANTS; m++) begin : variants
    req_master #(.RETRIES(RETRIES), .TIMEOUT(TIMEOUT), .MUTATION(m)) dut(
      .clk(clk), .rst_n(bus.rst_n),
      .cmd_valid(bus.cmd_valid), .cmd_write(bus.cmd_write), .cmd_addr(bus.cmd_addr), .cmd_wdata(bus.cmd_wdata), .cmd_ready(cmd_ready[m]),
      .req_valid(req_valid[m]), .req_write(req_write[m]), .req_addr(req_addr[m]), .req_wdata(req_wdata[m]), .req_ready(bus.req_ready),
      .rsp_valid(bus.rsp_valid), .rsp_err(bus.rsp_err), .rsp_rdata(bus.rsp_rdata),
      .done_valid(done_valid[m]), .done_err(done_err[m]), .done_timeout(done_timeout[m]), .done_rdata(done_rdata[m]), .done_tries(done_tries[m]));
  end
  assign bus.cmd_ready = cmd_ready[mutation];
  assign bus.req_valid = req_valid[mutation];
  assign bus.req_write = req_write[mutation];
  assign bus.req_addr = req_addr[mutation];
  assign bus.req_wdata = req_wdata[mutation];
  assign bus.done_valid = done_valid[mutation];
  assign bus.done_err = done_err[mutation];
  assign bus.done_timeout = done_timeout[mutation];
  assign bus.done_rdata = done_rdata[mutation];
  assign bus.done_tries = done_tries[mutation];

  // Bus-level bookkeeping for the cover properties: is a response outstanding, and for how long.
  bit waiting;
  int since;
  always @(posedge clk) begin
    if (!bus.rst_n) waiting <= 0;
    else if (bus.req_valid && bus.req_ready) begin waiting <= 1; since <= 0; end
    else if (waiting) begin
      if (bus.rsp_valid || since == TIMEOUT - 1) waiting <= 0;
      since <= since + 1;
    end
  end

  ap_hold: assert property (@(posedge clk) disable iff (!bus.rst_n || sva_off != 0)
    (bus.req_valid && !bus.req_ready) |=> (bus.req_valid && $stable({bus.req_write, bus.req_addr, bus.req_wdata})))
    else begin $display("CHECK_FAIL RX_HOLD"); $fatal(1, "request changed before it was accepted"); end

  cp_stall: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && bus.req_valid && !bus.req_ready) $display("RX_COVER cp_stall");
  cp_ok: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && bus.done_valid && !bus.done_err) $display("RX_COVER cp_ok");
  cp_error_rsp: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && waiting && bus.rsp_valid && bus.rsp_err) $display("RX_COVER cp_error_rsp");
  cp_retry_ok: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && bus.done_valid && !bus.done_err && bus.done_tries > 2'd1) $display("RX_COVER cp_retry_ok");
  cp_exhausted: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && bus.done_valid && bus.done_err && !bus.done_timeout) $display("RX_COVER cp_exhausted");
  cp_timeout: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && bus.done_valid && bus.done_timeout) $display("RX_COVER cp_timeout");
  cp_boundary: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && waiting && bus.rsp_valid && since == TIMEOUT - 1) $display("RX_COVER cp_boundary");
  cp_early: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && bus.rsp_valid && bus.req_valid && !bus.req_ready) $display("RX_COVER cp_early");
  cp_idle_rsp: cover property (@(posedge clk) sva_off == 0 && bus.rst_n && bus.rsp_valid && !bus.req_valid && !waiting) $display("RX_COVER cp_idle_rsp");
  cp_reset_busy: cover property (@(posedge clk) sva_off == 0 && !bus.rst_n && waiting) $display("RX_COVER cp_reset_busy");

  initial begin
    string wave, test;
    fatal_to_exit catcher;
    bus.rst_n = 0; bus.cmd_valid = 0; bus.cmd_write = 0; bus.cmd_addr = 0; bus.cmd_wdata = 0;
    bus.req_ready = 0; bus.rsp_valid = 0; bus.rsp_err = 0; bus.rsp_rdata = 0;
    void'($value$plusargs("MUTATION=%d", mutation));
    void'($value$plusargs("SVA_OFF=%d", sva_off));
    if (mutation < 0 || mutation >= VARIANTS || !$value$plusargs("WAVE=%s", wave) || !$value$plusargs("TEST=%s", test))
      $fatal(1, "invalid arguments");
    $dumpfile(wave); $dumpvars(0, top);
    catcher = new; uvm_report_cb::add(null, catcher);
    uvm_config_db #(virtual rx_if)::set(null, "uvm_test_top.env", "vif", bus);
    run_test(test);
  end
  initial begin #50000000; $fatal(1, "reactive watchdog"); end
endmodule
