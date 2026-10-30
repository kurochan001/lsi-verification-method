`timescale 1ns/1ps
module stream_tb;
  parameter integer WIDTH = 8;
  parameter integer DEPTH = 3;
  parameter integer MUTATION = 0;
  localparam [WIDTH-1:0] ONES = {WIDTH{1'b1}};
  reg clk = 0, rst_n = 0, s_valid = 0, m_ready = 0;
  reg [WIDTH-1:0] s_data = 0, vector_data;
  wire s_ready, m_valid;
  wire [WIDTH-1:0] m_data;
  // Linear reference queue; no access to DUT count, pointers or memory.
  reg [WIDTH-1:0] model [0:DEPTH-1];
  reg [WIDTH-1:0] before_data, held_source_data;
  integer count = 0, before_count, checks = 0, fd, fields, vr, vv, vready;
  integer accepted = 0, delivered = 0, flushed = 0, writes = 0, reads = 0;
  bit expected_ready, push, pop, stalled, source_held = 0;
  bit previous_stall = 0, previous_pop = 0, recovering = 0;
  string vectors, wave, state_name;
  stream_buffer #(.WIDTH(WIDTH), .DEPTH(DEPTH), .MUTATION(MUTATION)) dut (
    clk, rst_n, s_valid, s_ready, s_data, m_valid, m_ready, m_data
  );
  always #5 clk = !clk;
  task fail(input string label);
    begin
      $display("CHECK_FAIL %s", label);
      $fatal(1, "cycle=%0d reference_count=%0d s_valid=%b s_ready=%b m_valid=%b m_ready=%b m_data=%h",
             checks, count, s_valid, s_ready, m_valid, m_ready, m_data);
    end
  endtask
  task cycle;
    begin
      @(negedge clk);
      rst_n = vr; s_valid = vv; m_ready = vready; s_data = vector_data;
      #1;
      before_count = count;
      state_name = count == 0 ? "empty" : count == DEPTH ? "full" : "interior";
      expected_ready = count < DEPTH || (count > 0 && m_ready);
      push = rst_n && s_valid && expected_ready;
      pop = rst_n && count > 0 && m_ready;
      stalled = rst_n && count > 0 && !m_ready;
      before_data = m_data;
      if (rst_n) begin
        if (s_ready !== expected_ready) fail("STREAM_READY");
        if (m_valid !== (count > 0)) fail("STREAM_VALID");
        if (count > 0 && m_data !== model[0]) fail("STREAM_DATA");
        if (source_held && (!s_valid || s_data !== held_source_data)) fail("STREAM_SOURCE_HOLD");
      end
      @(posedge clk);
      if (!rst_n) begin
        recovering = count > 0;
        flushed = flushed + count; count = 0; writes = 0; reads = 0;
      end else begin
        if (pop) begin
          for (integer i = 0; i < count - 1; i = i + 1) model[i] = model[i + 1];
          count = count - 1; delivered = delivered + 1; reads = reads + 1;
        end
        if (push) begin
          model[count] = s_data; count = count + 1;
          accepted = accepted + 1; writes = writes + 1;
        end
      end
      #1;
      checks = checks + 1;
      if (stalled && (m_valid !== 1'b1 || m_data !== before_data)) fail("STREAM_STABILITY");
      if (m_valid !== (count > 0)) fail("STREAM_VALID");
      if (count > 0 && m_data !== model[0]) fail("STREAM_DATA");
      if (accepted != delivered + flushed + count) fail("STREAM_ACCOUNTING");
      // Observations are credited only after response, data and accounting pass.
      if (!rst_n) begin
        if (before_count == 0) $display("COVER reset/empty");
        else $display("COVER reset/nonempty");
        if (before_count > 0 && previous_stall) $display("COVER reset/stalled");
      end else begin
        $display("COVER cross/%s/valid%0d/ready%0d", state_name, s_valid, m_ready);
        if (stalled) $display("COVER stall/output");
        if (s_valid && !expected_ready) $display("COVER stall/input");
        if (previous_stall && pop) $display("COVER stall/resume");
        if (push && pop) $display("COVER flow/simultaneous");
        if (before_count == DEPTH && push && pop) $display("COVER flow/full-replace");
        if (previous_pop && pop) $display("COVER flow/consecutive");
        if (pop && count == 0) $display("COVER flow/drained");
        if (push && writes >= 2 * DEPTH) $display("COVER wrap/write");
        if (pop && reads >= 2 * DEPTH) $display("COVER wrap/read");
        if (pop) begin
          if (before_data == 0) $display("COVER data/zero");
          if (before_data == ONES) $display("COVER data/ones");
          if (before_data == ONES / 3) $display("COVER data/alternating");
          if (recovering) begin $display("COVER reset/recovery"); recovering = 0; end
        end
      end
      source_held = rst_n && s_valid && !expected_ready;
      held_source_data = s_data;
      previous_stall = stalled;
      previous_pop = pop;
    end
  endtask
  initial begin
    if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "Missing VECTORS");
    if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, stream_tb); end
    fd = $fopen(vectors, "r");
    if (!fd) $fatal(1, "Cannot open vectors");
    while (!$feof(fd)) begin
      fields = $fscanf(fd, "%d %d %d %h\n", vr, vv, vready, vector_data);
      if (fields != 4) fail("STREAM_VECTOR_FORMAT");
      cycle();
    end
    $fclose(fd);
    if (count != 0 || source_held) fail("STREAM_UNDRAINED");
    $display("COVER completion/drain");
    $display("ACCOUNTING accepted=%0d delivered=%0d flushed=%0d", accepted, delivered, flushed);
    $display("RESULT PASS checks=%0d", checks);
    $finish;
  end
endmodule
