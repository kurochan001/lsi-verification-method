`timescale 1ns/1ns
// Drives both designs from a vector file and compares the queue with the expected columns.
// The pattern checkers are attached by sva/bind_patterns.sv, not by this file.
// Vector (25 bits): in_valid, in_id[1:0], in_data[7:0], out_ready, evt,
//                   expected in_ready, out_valid, out_id[1:0], out_data[7:0].
module dut_tb #(parameter MUTATION = 0, parameter LAT = 1);
  localparam MAX = 4096;
  bit clk = 0, clk_b = 0;
  logic rst_n = 0, rst_b_n = 0;
  logic [24:0] rom [0:MAX-1];
  logic [24:0] row;
  int cycles, half_b, index = 0, mismatches = 0, accepted = 0, notes = 0, checked = 0;
  string vector_file;

  logic in_valid = 0, out_ready = 0, evt = 0;
  logic [1:0] in_id = 0;
  logic [7:0] in_data = 0;
  logic in_ready, out_valid, evt_ready, note_b;
  logic [1:0] out_id;
  logic [7:0] out_data;

  tagged_queue #(.DATA_W(8), .LAT(LAT), .MUTATION(MUTATION)) u_queue (
    .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_ready(in_ready), .in_id(in_id),
    .in_data(in_data), .out_valid(out_valid), .out_ready(out_ready), .out_id(out_id),
    .out_data(out_data));
  event_cross #(.MUTATION(MUTATION)) u_cross (
    .clk(clk), .rst_n(rst_n), .evt(evt), .evt_ready(evt_ready), .clk_b(clk_b),
    .rst_b_n(rst_b_n), .note_b(note_b));

  always #10 clk = ~clk;
  initial begin
    if (!$value$plusargs("VECTORS=%s", vector_file)) $fatal(1, "VECTORS missing");
    if (!$value$plusargs("CYCLES=%d", cycles)) $fatal(1, "CYCLES missing");
    if (!$value$plusargs("HALF_B=%d", half_b)) half_b = 7;
    $readmemh(vector_file, rom);
    forever #(half_b) clk_b = ~clk_b;
  end

  // Inputs change on the falling edge, away from every sampling edge of clk.
  always @(negedge clk) begin
    if (index == 3) begin
      rst_n <= 1;
      rst_b_n <= 1;
    end
    if (index >= 4 && index - 4 < cycles) begin
      row = rom[index - 4];
      {in_valid, in_id, in_data, out_ready, evt} <= row[24:12];
    end else begin
      row = '0;
      {in_valid, in_id, in_data, out_ready, evt} <= '0;
    end
    index <= index + 1;
    if (index == cycles + 40) begin
      // Every accepted event must have produced exactly one note by now.
      if (notes != accepted) begin
        $display("CHECK_FAIL CROSS_COUNT accepted=%0d notes=%0d", accepted, notes);
        mismatches++;
      end
      $display("COUNT checked=%0d", checked);
      $display("COUNT accepted=%0d", accepted);
      $display("COUNT mismatches=%0d", mismatches);
      $display("RESULT %s", mismatches == 0 ? "PASS" : "FAIL");
      $finish;
    end
  end

  always @(posedge clk) if (rst_n && index > 4 && index - 5 < cycles) begin
    checked++;
    if (in_ready !== row[11] || out_valid !== row[10] ||
        (row[10] && {out_id, out_data} !== row[9:0])) begin
      if (mismatches < 5)
        $display("CHECK_FAIL QUEUE_MODEL cycle=%0d got=%b%b%h expected=%b%b%h", index - 5,
                 in_ready, out_valid, {out_id, out_data}, row[11], row[10], row[9:0]);
      mismatches++;
    end
    if (evt && evt_ready) accepted++;
  end
  always @(posedge clk_b) if (rst_b_n && note_b) notes++;
endmodule
