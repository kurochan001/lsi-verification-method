`timescale 1ns/1ps
module reduction_tb;
  parameter integer MUTATION = 0;
  reg clk = 0, rst_n = 0, event_accept = 0, clear_accept = 0, irq_en = 0;
  wire pend, irq;
  bit model_pending = 0, before_pending, recovering = 0;
  integer checks = 0, fd, fields, vr, ve, vc, vi, event_streak = 0;
  string vectors;
  reduction_irq #(.MUTATION(MUTATION)) dut (
    clk, rst_n, event_accept, clear_accept, irq_en, pend, irq
  );
  always #5 clk = !clk;
  task fail(input string label);
    begin
      $display("CHECK_FAIL %s", label);
      $fatal(1, "cycle=%0d expected_pending=%b pending=%b irq=%b", checks, model_pending, pend, irq);
    end
  endtask
  initial begin
    if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "Missing VECTORS");
    fd = $fopen(vectors, "r");
    if (!fd) $fatal(1, "Cannot open vectors");
    while (!$feof(fd)) begin
      fields = $fscanf(fd, "%d %d %d %d\n", vr, ve, vc, vi);
      if (fields != 4) fail("REDUCTION_VECTOR_FORMAT");
      @(negedge clk);
      rst_n = vr != 0; event_accept = ve != 0; clear_accept = vc != 0; irq_en = vi != 0;
      before_pending = model_pending;
      @(posedge clk);
      if (!rst_n) begin
        recovering = before_pending; model_pending = 0; event_streak = 0;
      end else begin
        if (event_accept) model_pending = 1;
        else if (clear_accept) model_pending = 0;
        if (event_accept) event_streak = event_streak + 1;
        else event_streak = 0;
      end
      #1; checks = checks + 1;
      if (pend !== model_pending) begin
        if (!rst_n) fail("IRQ_RESET");
        else if (event_accept && clear_accept) fail("IRQ_SET_WINS");
        else if (event_accept) fail("IRQ_SET_ONLY");
        else if (clear_accept) fail("IRQ_CLEAR_ONLY");
        else fail("IRQ_HOLD");
      end
      if (irq !== (model_pending && irq_en)) fail("IRQ_OUTPUT");
      if (!rst_n) begin
        if (before_pending) $display("COVER reset/nonempty");
        else $display("COVER reset/empty");
      end else begin
        $display("COVER atomic/p%0d/en%0d/op%0d", before_pending, irq_en,
                 event_accept + 2 * clear_accept);
        if (recovering && event_accept) begin
          $display("COVER reset/recovery"); recovering = 0;
        end
        if (event_streak >= 9 && clear_accept) $display("COVER stress/long-history");
      end
    end
    $fclose(fd);
    $display("RESULT PASS checks=%0d", checks);
    $finish;
  end
endmodule
