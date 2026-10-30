`timescale 1ns/1ps
module sva_tb(output wire failed);
  reg clk = 0, rst_n = 0, event_accept = 0, clear_accept = 0, irq_en = 0;
  reg fault = 0, launch = 0;
  wire [3:0] pending_values, irq_values;
  wire observed_pending, observed_irq;
  integer mutation, selftest, checker_off, planned, checks = 0;
  integer fd, fields, vr, ve, vc, vi, vf;
  string vectors, wave;
  for (genvar g = 0; g < 4; g = g + 1) begin : variants
    irq_pending #(.MUTATION(g)) dut (
      clk, rst_n, event_accept, clear_accept, irq_en, pending_values[g], irq_values[g]
    );
  end
  // Checker-only faults exercise the remaining three assertion action blocks.
  assign observed_pending = fault && selftest == 1 ? 1'b1 :
                            fault && selftest == 2 ? !pending_values[mutation] : pending_values[mutation];
  assign observed_irq = fault && selftest == 3 ? !irq_values[mutation] : irq_values[mutation];
  irq_checker checker_inst (
    clk, rst_n, checker_off == 0, launch,
    event_accept, clear_accept, observed_pending, irq_en, observed_irq, failed
  );
  always #5 clk = !clk;
  initial begin
    if (!$value$plusargs("VECTORS=%s", vectors) ||
        !$value$plusargs("CHECKS=%d", planned) ||
        !$value$plusargs("MUTATION=%d", mutation) ||
        !$value$plusargs("SELFTEST=%d", selftest) ||
        !$value$plusargs("CHECKER_OFF=%d", checker_off)) $fatal(1, "Missing arguments");
    if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, sva_tb); end
    fd = $fopen(vectors, "r");
    if (fd == 0) $fatal(1, "Cannot open vectors");
    while (!$feof(fd)) begin
      fields = $fscanf(fd, "%d %d %d %d %d\n", vr, ve, vc, vi, vf);
      if (fields != 5) $fatal(1, "Bad vector format");
      @(negedge clk);
      rst_n = vr != 0; event_accept = ve != 0; clear_accept = vc != 0;
      irq_en = vi != 0; fault = vf != 0;
      // Last clock observes all previous one-cycle obligations; it starts none.
      launch = checks < planned - 1;
      @(posedge clk); #1;
      checks = checks + 1;
      if (failed) break;
    end
    $fclose(fd);
    if (failed) begin
      $finish;
    end else if (checks != planned || launch || !rst_n || event_accept || clear_accept || fault) begin
      $fatal(1, "Missing final observation cycle");
    end else begin
      $display("RESULT PASS checks=%0d", checks);
      $finish;
    end
  end
endmodule
