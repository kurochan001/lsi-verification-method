`timescale 1ns/1ps

module fifo_tb;
  parameter integer WIDTH = 8;
  parameter integer DEPTH = 3;
  parameter integer MUTATION = 0;
  localparam integer COUNT_WIDTH = $clog2(DEPTH + 1);
  localparam [WIDTH-1:0] ONES = {WIDTH{1'b1}};
  localparam [WIDTH-1:0] ALTERNATING = ONES / 3;

  reg clk = 0, rst_n = 0, wr_en = 0, rd_en = 0;
  reg [WIDTH-1:0] wr_data = 0;
  wire [WIDTH-1:0] rd_data;
  wire rd_valid, full, empty;
  wire [COUNT_WIDTH-1:0] count;
  // Independent reference: shift a linear queue; do not copy DUT pointers.
  reg [WIDTH-1:0] model [0:DEPTH-1];
  reg [WIDTH-1:0] expected_output = 0;
  reg [WIDTH-1:0] vector_data;
  integer model_count = 0, before_count, index, checks = 0;
  integer accepted_writes = 0, accepted_reads = 0;
  integer fd, fields, reset_value, write_value, read_value;
  bit push, pop, recovery_pending = 0;
  string vectors, wave, state_name;

  sync_fifo #(.WIDTH(WIDTH), .DEPTH(DEPTH), .MUTATION(MUTATION)) dut (
    clk, rst_n, wr_en, rd_en, wr_data, rd_data, rd_valid, full, empty, count
  );
  always #5 clk = !clk;

  task fail(input string label);
    begin
      $display("CHECK_FAIL %s", label);
      $fatal(1, "cycle=%0d expected_count=%0d actual_count=%0d expected_data=%h actual_data=%h",
             checks, model_count, count, expected_output, rd_data);
    end
  endtask

  task cycle;
    begin
      @(negedge clk);
      rst_n = reset_value != 0;
      wr_en = write_value != 0;
      rd_en = read_value != 0;
      wr_data = vector_data;
      before_count = model_count;
      state_name = before_count == 0 ? "empty" :
                   before_count == DEPTH ? "full" : "interior";
      push = rst_n && wr_en && before_count < DEPTH;
      pop = rst_n && rd_en && before_count > 0;
      if (!rst_n) begin
        if (before_count > 0) recovery_pending = 1;
        model_count = 0;
        expected_output = 0;
        accepted_writes = 0;
        accepted_reads = 0;
      end else begin
        if (pop) begin
          expected_output = model[0];
          for (index = 0; index < model_count - 1; index = index + 1)
            model[index] = model[index + 1];
          model_count = model_count - 1;
          accepted_reads = accepted_reads + 1;
        end
        if (push) begin
          model[model_count] = wr_data;
          model_count = model_count + 1;
          accepted_writes = accepted_writes + 1;
        end
      end
      @(posedge clk);
      #1;  // Compare registered outputs after NBA updates.
      checks = checks + 1;
      if ((^{count, full, empty, rd_valid, rd_data}) === 1'bx)
        fail("FIFO_UNKNOWN");
      if (!rst_n && (count !== 0 || rd_data !== 0 || rd_valid !== 0 ||
                     empty !== 1 || full !== 0)) fail("FIFO_RESET");
      if (count !== model_count) fail("FIFO_COUNT");
      if (full !== (model_count == DEPTH) || empty !== (model_count == 0))
        fail("FIFO_FLAGS");
      if (rd_valid !== pop) fail("FIFO_READ_VALID");
      if (rd_data !== expected_output) fail("FIFO_DATA_ORDER");

      // Emit coverage only AFTER every checker for this cycle passed.
      if (!rst_n) begin
        if (before_count == 0) $display("COVER reset/empty");
        else $display("COVER reset/nonempty");
      end else begin
        $display("COVER cross/%s/op%0d", state_name, wr_en + 2 * rd_en);
        if (wr_en && before_count == DEPTH) $display("COVER blocked/write-full");
        if (rd_en && before_count == 0) $display("COVER blocked/read-empty");
        if (push && accepted_writes % DEPTH == 0) $display("COVER wrap/write");
        if (pop && accepted_reads % DEPTH == 0) $display("COVER wrap/read");
        if (pop) begin
          if (rd_data == 0) $display("COVER data/zero");
          if (rd_data == ONES) $display("COVER data/ones");
          if (rd_data == ALTERNATING) $display("COVER data/alternating");
          if (recovery_pending) begin
            $display("COVER reset/recovery");
            recovery_pending = 0;
          end
        end
      end
    end
  endtask

  initial begin
    if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "Missing VECTORS");
    if ($value$plusargs("WAVE=%s", wave)) begin
      $dumpfile(wave);
      $dumpvars(0, fifo_tb);
    end
    fd = $fopen(vectors, "r");
    if (fd == 0) $fatal(1, "Cannot open vectors");
    fields = $fscanf(fd, "%d %d %d %h\n", reset_value, write_value, read_value, vector_data);
    while (fields == 4) begin
      cycle();
      fields = $fscanf(fd, "%d %d %d %h\n", reset_value, write_value, read_value, vector_data);
    end
    if (!$feof(fd) || checks == 0) $fatal(1, "Malformed/empty vector file");
    $fclose(fd);
    if (model_count != 0) fail("FIFO_NOT_DRAINED");
    $display("RESULT PASS checks=%0d", checks);
    $finish;
  end
endmodule
