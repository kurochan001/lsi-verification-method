`timescale 1ns/1ps

module irq_tb;
  parameter integer MUTATION = 0;
  reg clk = 0;
  reg rst_n = 0;
  reg event_accept = 0;
  reg clear_accept = 0;
  reg irq_en = 0;
  wire pend, irq;
  reg expected_pend = 0;
  integer checks = 0;
  integer initial_pend, enable_value, operation, event_edge;
  integer step, vector_fd, fields, ev, cl, en, vector_count;
  string mode, wave_path, vector_path;

  irq_pending #(.MUTATION(MUTATION)) dut (
    .clk(clk), .rst_n(rst_n), .event_accept(event_accept),
    .clear_accept(clear_accept), .irq_en(irq_en), .pend(pend), .irq(irq)
  );
  always #5 clk = !clk;

  // Drive on the falling edge; compare after the rising edge's NBA updates.
  // The reference is derived from the specification, not the DUT's outputs.
  task cycle(input bit e, input bit c, input bit reset_n, input bit enabled);
    string label;
    begin
      @(negedge clk);
      event_accept = e;
      clear_accept = c;
      rst_n = reset_n;
      irq_en = enabled;
      if (!reset_n) begin
        expected_pend = 0;
        label = "IRQ_RESET";
      end else if (e) begin
        expected_pend = 1;
        label = c ? "IRQ_SET_WINS" : "IRQ_SET_ONLY";
      end else if (c) begin
        expected_pend = 0;
        label = "IRQ_CLEAR_ONLY";
      end else begin
        label = "IRQ_HOLD";
      end
      @(posedge clk);
      #1;
      checks = checks + 1;
      if (pend !== expected_pend) begin
        $display("CHECK_FAIL %s", label);
        $fatal(1, "pend expected=%b actual=%b checks=%0d", expected_pend, pend, checks);
      end
      if (irq !== (expected_pend && enabled)) begin
        $display("CHECK_FAIL IRQ_OUTPUT");
        $fatal(1, "irq expected=%b actual=%b", expected_pend && enabled, irq);
      end
    end
  endtask

  initial begin
    if (!$value$plusargs("MODE=%s", mode) ||
        !$value$plusargs("INITIAL=%d", initial_pend) ||
        !$value$plusargs("ENABLE=%d", enable_value))
      $fatal(1, "Missing required case arguments");
    if ($value$plusargs("WAVE=%s", wave_path)) begin
      $dumpfile(wave_path);
      $dumpvars(0, irq_tb);
    end
    cycle(0, 0, 0, 1);
    cycle(initial_pend != 0, 0, 1, 1);
    if (mode == "atomic") begin
      if (!$value$plusargs("OP=%d", operation)) $fatal(1, "Missing OP");
      cycle((operation & 1) != 0, (operation & 2) != 0, 1, enable_value != 0);
    end else if (mode == "cross") begin
      if (!$value$plusargs("EVENT_EDGE=%d", event_edge)) $fatal(1, "Missing EVENT_EDGE");
      for (step = -1; step <= 1; step = step + 1)
        cycle(step == event_edge, step == 0, 1, enable_value != 0);
    end else if (mode == "random") begin
      if (!$value$plusargs("VECTORS=%s", vector_path)) $fatal(1, "Missing VECTORS");
      vector_fd = $fopen(vector_path, "r");
      if (vector_fd == 0) $fatal(1, "Cannot open vector file");
      vector_count = 0;
      while (!$feof(vector_fd)) begin
        fields = $fscanf(vector_fd, "%d %d %d\n", ev, cl, en);
        if (fields == 3) begin
          cycle(ev != 0, cl != 0, 1, en != 0);
          vector_count = vector_count + 1;
        end else if (!$feof(vector_fd)) begin
          $fatal(1, "Malformed vector file");
        end
      end
      $fclose(vector_fd);
      if (vector_count == 0) $fatal(1, "Empty vector file");
    end else begin
      $fatal(1, "Unknown MODE");
    end
    $display("RESULT PASS checks=%0d", checks);
    $finish;
  end
endmodule
