`timescale 1ns/1ps
module arbiter_tb;
  parameter integer PORTS = 3;
  parameter integer MUTATION = 0;
  // Disabled only in an isolated fairness-monitor self-test.
  parameter integer CHECK_ORDER = 1;
  reg clk = 0, rst_n = 0, ready = 0;
  reg [PORTS-1:0] req = 0, vector_req, source_held = 0, previous_req = 0;
  wire [PORTS-1:0] grant;
  reg [PORTS-1:0] expected, sampled_grant, previous_grant = 0;
  integer order [0:PORTS-1];
  integer rotated [0:PORTS-1];
  integer serviced [0:PORTS-1];
  integer wall_wait [0:PORTS-1];
  integer other_services [0:PORTS-1];
  integer port_max_wall [0:PORTS-1];
  integer port_max_service [0:PORTS-1];
  integer lock_port = -1, winner, position, previous_winner = -1;
  integer checks = 0, accepted = 0, opportunities = 0, blocked = 0, cancelled = 0;
  integer max_wall = 0, max_service_wait = 0, full_window = 0;
  integer fd, fields, vr, vready;
  bit previous_stall = 0, recovering = 0, all_serviced;
  string vectors, wave;
  rr_arbiter #(.PORTS(PORTS), .MUTATION(MUTATION)) dut (clk, rst_n, req, ready, grant);
  always #5 clk = !clk;
  task fail(input string label);
    begin
      $display("CHECK_FAIL %s", label);
      $fatal(1, "cycle=%0d req=%h grant=%h expected=%h", checks, req, grant, expected);
    end
  endtask
  initial begin
    for (integer p = 0; p < PORTS; p = p + 1) begin
      order[p] = p; serviced[p] = 0; wall_wait[p] = 0; other_services[p] = 0;
      port_max_wall[p] = 0; port_max_service[p] = 0;
    end
    if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "Missing VECTORS");
    if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, arbiter_tb); end
    fd = $fopen(vectors, "r");
    if (!fd) $fatal(1, "Cannot open vectors");
    while (!$feof(fd)) begin
      fields = $fscanf(fd, "%d %h %d\n", vr, vector_req, vready);
      if (fields != 3) fail("ARB_VECTOR_FORMAT");
      @(negedge clk);
      rst_n = vr != 0; req = vector_req; ready = vready != 0;
      #1;
      expected = 0;
      if (lock_port >= 0) expected[lock_port] = 1;
      else begin
        for (integer p = 0; p < PORTS; p = p + 1)
          if (expected == 0 && req[order[p]]) expected[order[p]] = 1;
      end
      winner = -1;
      if (rst_n) begin
        if ((req & source_held) !== source_held) fail("ARB_SOURCE_HOLD");
        if ((^grant) === 1'bx) fail("ARB_UNKNOWN");
        if ((grant & (grant - 1'b1)) != 0) fail("ARB_ONEHOT");
        if ((grant & ~req) != 0) fail("ARB_REQUEST");
        if (previous_stall && grant !== previous_grant) fail("ARB_STABILITY");
        if (req != 0 && grant == 0) fail("ARB_IDLE");
        if (CHECK_ORDER && grant !== expected) fail("ARB_ORDER");
        for (integer p = 0; p < PORTS; p = p + 1) if (grant[p]) winner = p;
      end
      sampled_grant = grant;
      @(posedge clk);
      if (!rst_n) begin
        recovering = source_held != 0;
        lock_port = -1; previous_winner = -1; full_window = 0;
        for (integer p = 0; p < PORTS; p = p + 1) begin
          order[p] = p;
          if (wall_wait[p] > 0) cancelled = cancelled + 1;
          wall_wait[p] = 0; other_services[p] = 0;
        end
      end else begin
        if (req != 0 && ready) opportunities = opportunities + 1;
        if (winner >= 0 && !ready) begin blocked = blocked + 1; lock_port = winner; end
        if (winner >= 0 && ready) begin
          accepted = accepted + 1; serviced[winner] = serviced[winner] + 1;
          for (integer p = 0; p < PORTS; p = p + 1) if (order[p] == winner) position = p;
          for (integer p = 0; p < PORTS; p = p + 1) rotated[p] = order[(position + 1 + p) % PORTS];
          for (integer p = 0; p < PORTS; p = p + 1) order[p] = rotated[p];
          lock_port = -1;
        end
        for (integer p = 0; p < PORTS; p = p + 1) begin
          if (!req[p]) begin wall_wait[p] = 0; other_services[p] = 0; end
          else begin
            wall_wait[p] = wall_wait[p] + 1;
            if (wall_wait[p] > port_max_wall[p]) port_max_wall[p] = wall_wait[p];
            if (wall_wait[p] > max_wall) max_wall = wall_wait[p];
            if (winner >= 0 && ready) begin
              if (winner == p) begin
                if (other_services[p] + 1 > port_max_service[p]) port_max_service[p] = other_services[p] + 1;
                if (other_services[p] + 1 > max_service_wait) max_service_wait = other_services[p] + 1;
                wall_wait[p] = 0; other_services[p] = 0;
              end else begin
                other_services[p] = other_services[p] + 1;
                if (other_services[p] >= PORTS) fail("ARB_FAIRNESS");
              end
            end
          end
        end
        if (&req && ready) full_window = full_window + 1;
        else full_window = 0;
      end
      #1; checks = checks + 1;
      // Emit coverage only after the ordering and independent fairness checks.
      if (!rst_n) begin
        if (source_held == 0) $display("COVER reset/idle");
        else $display("COVER reset/pending");
      end else begin
        $display("COVER mask/%0d/ready%0d", req, ready);
        if (winner >= 0 && !ready) $display("COVER stall/active");
        if (previous_stall && |(req & ~previous_req)) $display("COVER stall/new-arrival");
        if (previous_stall && winner >= 0 && ready) $display("COVER stall/resume");
        if (full_window >= PORTS) $display("COVER fair/window-complete");
        if (winner >= 0 && ready) begin
          $display("COVER serve/port%0d", winner);
          if (previous_winner >= 0 && winner == (previous_winner + 1) % PORTS)
            $display("COVER rotate/from%0d/to%0d", previous_winner, winner);
          previous_winner = winner;
          if (recovering) begin $display("COVER reset/recovery"); recovering = 0; end
        end
      end
      source_held = !rst_n ? 0 : req & ~(ready ? sampled_grant : {PORTS{1'b0}});
      previous_stall = rst_n && winner >= 0 && !ready;
      previous_req = req; previous_grant = sampled_grant;
    end
    $fclose(fd);
    if (source_held != 0 || req != 0) fail("ARB_UNRESOLVED");
    all_serviced = 1;
    for (integer p = 0; p < PORTS; p = p + 1) begin
      if (serviced[p] == 0) all_serviced = 0;
      $display("SERVICE port=%0d count=%0d max_wall=%0d max_service_wait=%0d",
               p, serviced[p], port_max_wall[p], port_max_service[p]);
    end
    if (all_serviced) $display("COVER fair/all-ports");
    $display("COVER completion/drain");
    $display("METRICS opportunities=%0d accepted=%0d blocked=%0d max_wall=%0d max_service_wait=%0d cancelled=%0d",
             opportunities, accepted, blocked, max_wall, max_service_wait, cancelled);
    $display("RESULT PASS checks=%0d", checks);
    $finish;
  end
endmodule
