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
  integer scenario, before_pend, observed_event, observed_clear;
  reg src_clk = 0;
  reg async_value = 0;
  integer delay_a = 2, delay_b = 2;
  wire cdc_a, cdc_b;
  wire accepted_toggle, accepted_pulse;
  integer elapsed, latency_a, latency_b, da, db;
  string mode, wave_path, vector_path;

  irq_pending #(.MUTATION(MUTATION)) dut (
    .clk(clk), .rst_n(rst_n), .event_accept(event_accept),
    .clear_accept(clear_accept), .irq_en(irq_en), .pend(pend), .irq(irq)
  );
  always #5 clk = !clk;
  always #7 src_clk = !src_clk;
  cdc_delay_model sync_a(clk, rst_n, async_value, delay_a, cdc_a);
  cdc_delay_model sync_b(clk, rst_n, async_value, delay_b, cdc_b);
  cdc_receiver #(.EARLY_A_ONLY(MUTATION == 4)) receiver(
    clk, rst_n, cdc_a, cdc_b, accepted_toggle, accepted_pulse
  );

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
      if ((^{pend, irq}) === 1'bx) begin
        if (mode == "x" && pend === 1'bx && irq === 1'bx)
          $display("COVER x/propagation-detected");
        $display("CHECK_FAIL IRQ_OUTPUT_UNKNOWN");
        $fatal(1, "unknown state/output in a valid observation period");
      end
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
      before_pend = pend;
      cycle((operation & 1) != 0, (operation & 2) != 0, 1, enable_value != 0);
      $display("COVER atomic/p%0d/en%0d/op%0d", before_pend, irq_en,
               event_accept + 2 * clear_accept);
    end else if (mode == "cross") begin
      if (!$value$plusargs("EVENT_EDGE=%d", event_edge)) $fatal(1, "Missing EVENT_EDGE");
      before_pend = pend;
      observed_event = 99;
      observed_clear = 99;
      for (step = -1; step <= 1; step = step + 1) begin
        cycle(step == event_edge, step == 0, 1, enable_value != 0);
        if (event_accept) observed_event = step;
        if (clear_accept) observed_clear = step;
      end
      $display("COVER cross/p%0d/en%0d/edge%0d", before_pend, irq_en,
               observed_event - observed_clear);
    end else if (mode == "reset") begin
      if (!$value$plusargs("SCENARIO=%d", scenario)) $fatal(1, "Missing SCENARIO");
      cycle(1, 0, 1, 1);
      cycle(0, 0, 1, scenario != 2);
      cycle(scenario == 1, scenario == 1, 0, scenario != 2);
      cycle(0, 0, 1, scenario != 2);
      cycle(1, 0, 1, 1);
      $display("COVER reset/scenario%0d", scenario);
    end else if (mode == "x") begin
      cycle(1, 0, 1, 1);
      force dut.pend = 1'bx;
      cycle(0, 0, 1, 1);
      release dut.pend;
      $fatal(1, "X checker did not detect the injected value");
    end else if (mode == "cdc") begin
      if (!$value$plusargs("VECTORS=%s", vector_path)) $fatal(1, "Missing VECTORS");
      vector_fd = $fopen(vector_path, "r");
      if (vector_fd == 0) $fatal(1, "Cannot open CDC vector file");
      vector_count = 0;
      while (!$feof(vector_fd)) begin
        fields = $fscanf(vector_fd, "%d %d\n", da, db);
        if (fields == 2) begin
          @(negedge src_clk);
          delay_a = da;
          delay_b = db;
          async_value = !async_value;
          latency_a = 0;
          latency_b = 0;
          for (elapsed = 1; elapsed <= (da > db ? da : db); elapsed = elapsed + 1) begin
            @(posedge clk);
            #1;
            checks = checks + 1;
            if (cdc_a === async_value && latency_a == 0) latency_a = elapsed;
            if (cdc_b === async_value && latency_b == 0) latency_b = elapsed;
            if (cdc_a !== (elapsed >= da ? async_value : !async_value)) begin
              $display("CHECK_FAIL CDC_LATENCY_A");
              $fatal(1, "incorrect CDC A delivery time");
            end
            if (cdc_b !== (elapsed >= db ? async_value : !async_value)) begin
              $display("CHECK_FAIL CDC_LATENCY_B");
              $fatal(1, "incorrect CDC B delivery time");
            end
            if (accepted_pulse !== 1'b0) begin
              $display("CHECK_FAIL CDC_RECEIVER_EARLY");
              $fatal(1, "receiver accepted before both paths settled");
            end
          end
          @(posedge clk);
          #1;
          checks = checks + 1;
          if (accepted_pulse !== 1'b1 || accepted_toggle !== async_value) begin
            $display("CHECK_FAIL CDC_RECEIVER_DELIVERY");
            $fatal(1, "receiver missed or corrupted the event");
          end
          @(posedge clk);
          #1;
          checks = checks + 1;
          if (accepted_pulse !== 1'b0 || accepted_toggle !== async_value) begin
            $display("CHECK_FAIL CDC_RECEIVER_DUPLICATE");
            $fatal(1, "receiver repeated the event");
          end
          $display("COVER cdc/a%0d/b%0d/value%0d", latency_a - 2, latency_b - 2,
                   async_value);
          vector_count = vector_count + 1;
        end else if (!$feof(vector_fd)) begin
          $fatal(1, "Malformed CDC vector file");
        end
      end
      $fclose(vector_fd);
      if (vector_count == 0) $fatal(1, "Empty CDC vector file");
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
