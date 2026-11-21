`timescale 1ps/1ps
// Three CAN nodes with unequal clocks on one wired-AND bus. The script comes from the Python model:
// it requests frames, disturbs the bus or one node's view of it, and states what must be seen.
// The bus is checked as run lengths measured in nominal bit times, independently of any node.
module can_tb;
  parameter integer TSEG1 = 13;
  parameter integer TSEG2 = 6;
  parameter integer SJW = 4;
  parameter integer SKEW = 8;       // clock error of the two unequal nodes, in units of 0.1 %
  parameter integer PATTERN = 0;    // which nodes run fast and slow
  parameter integer MUTATION = 0;
  localparam integer NTQ = 1 + TSEG1 + TSEG2;
  localparam integer TQ = 2000;
  localparam integer BITT = NTQ * TQ;
  localparam integer NGOALS = 36;
  localparam [3:0] OP_RESET = 0, OP_NODE = 1, OP_START = 2, OP_INJ = 3, OP_TXREQ = 4, OP_RUN = 5, OP_RX = 6,
                   OP_ERR = 7, OP_DONE = 8, OP_END = 9, OP_STATE = 10, OP_LOST = 11, OP_WAIT = 12;

  reg [2:0] clk = 0, rstn = 0;
  reg mclk = 0;
  wire [2:0] txo, tx_ready, tx_done, rx_valid, rx_rtr, err_valid, arb_lost;
  wire [10:0] rx_id [0:2];
  wire [3:0] rx_dlc [0:2];
  wire [63:0] rx_data [0:2];
  wire [2:0] err_code [0:2];
  wire [1:0] sync_kind [0:2];
  wire [8:0] tec [0:2];
  wire [7:0] rec [0:2];
  wire [1:0] mode [0:2];
  reg [2:0] tx_valid = 0;
  reg [79:0] tx_word [0:2];

  // ---- bus and disturbances
  reg force_dom = 0;
  reg [2:0] view_dom = 0, view_rec = 0;
  wire bus = (&txo) && !force_dom;
  wire [2:0] rxi = ({3{bus}} & ~view_dom) | view_rec;

  function integer half(input integer node);
    integer delta;
    begin
      delta = 0;
      if (PATTERN == 0) delta = node == 1 ? SKEW : node == 2 ? -SKEW : 0;
      else delta = node == 0 ? SKEW : node == 1 ? -SKEW : 0;
      half = TQ / 2 + delta;
    end
  endfunction
  initial begin #137; forever #(half(0)) clk[0] = !clk[0]; end
  initial begin #411; forever #(half(1)) clk[1] = !clk[1]; end
  initial begin #733; forever #(half(2)) clk[2] = !clk[2]; end
  initial begin #59; forever #(TQ / 2) mclk = !mclk; end

  // ---- script state
  integer fd, fields, checks = 0, i, k;
  reg [3:0] op;
  reg [63:0] fa, fb, fc, fd_, fe;
  string vectors, wave;
  integer frames = 0, errors = 0, done_total = 0, runs_checked = 0;
  reg [NGOALS-1:0] goal = 0;

  task fail(input string label);
    begin
      $display("CHECK_FAIL %s", label);
      $fatal(1, "row=%0d op=%0d a=%h b=%h c=%h d=%h e=%h time=%0t", checks, op, fa, fb, fc, fd_, fe, $time);
    end
  endtask

  // ---- bus monitor: run lengths in nominal bit times, counted from the first dominant edge
  reg started = 0, acc_valid = 0, acc_level = 0, prev_bus = 1, last_ok = 0;
  time t_last = 0;
  integer bits_seen = 0, seg, qh = 0, qt = 0, acc_total = 0;
  reg run_level [0:8191];
  integer run_count [0:8191];
  task push_run(input level, input integer count);
    begin
      run_level[qt] = level; run_count[qt] = count; qt = (qt + 1) % 8192;
      if (qt == qh) fail("CAN_OVERFLOW");
    end
  endtask
  always @(bus) begin
    if (bus === 1'bx) fail("CAN_UNKNOWN");
    if (!started) begin
      if (!bus) begin
        started = 1; t_last = $time; bits_seen = 0; acc_valid = 0;
      end
    end else begin
      seg = ($time - t_last + BITT / 2) / BITT;
      if (seg > 0) begin                              // shorter pieces are glitches between two drivers
        if (acc_valid && acc_level == prev_bus) acc_total = acc_total + seg;
        else begin
          if (acc_valid) push_run(acc_level, acc_total);
          acc_valid = 1; acc_level = prev_bus; acc_total = seg;
        end
        if (prev_bus && seg == 11 && last_ok) goal[7] = 1;
        bits_seen = bits_seen + seg;
        t_last = $time;
      end
    end
    prev_bus = bus;
  end

  // Wait for the next completed run. A run is complete when the other level has followed it for most of a bit.
  task next_run(output level, output integer count);
    integer waited;
    begin
      waited = 0;
      while (qh == qt) begin
        @(posedge mclk);
        waited = waited + 1;
        if (started && acc_valid && bus !== acc_level && ($time - t_last) > (BITT * 3) / 4) begin
          push_run(acc_level, acc_total);
          acc_valid = 0;
        end
        if (waited > 4000 * NTQ) fail("CAN_TIMEOUT");
      end
      level = run_level[qh]; count = run_count[qh]; qh = (qh + 1) % 8192;
    end
  endtask

  // ---- disturbances, placed by bit number since the first dominant edge of the scenario
  reg [1:0] inj_kind [0:255];
  reg [1:0] inj_node [0:255];
  // The rows arrive in the order of their first bit, and at most two overlap.
  integer inj_start [0:255], inj_len [0:255], inj_n = 0, inj_lo = 0, pos, j;
  reg next_force;
  reg [2:0] next_dom, next_rec;
  always @(posedge mclk) begin
    next_force = 0; next_dom = 0; next_rec = 0;
    if (started && inj_lo < inj_n) begin
      pos = bits_seen * NTQ + ($time - t_last) / TQ;
      while (inj_lo < inj_n && pos >= (inj_start[inj_lo] + inj_len[inj_lo]) * NTQ + 2) inj_lo = inj_lo + 1;
      for (j = inj_lo; j < inj_n && j < inj_lo + 2; j = j + 1)
        if (pos >= inj_start[j] * NTQ + 2 && pos < (inj_start[j] + inj_len[j]) * NTQ + 2) begin
          if (inj_kind[j] == 0) next_force = 1;
          else if (inj_kind[j] == 1) next_dom[inj_node[j]] = 1;
          else next_rec[inj_node[j]] = 1;
        end
    end
    force_dom <= next_force; view_dom <= next_dom; view_rec <= next_rec;
  end

  // ---- nodes, request drivers and observers
  reg [79:0] reqq [0:2][0:63];
  integer rh [0:2], rt [0:2];
  reg [79:0] rxq [0:2][0:255];
  reg [2:0] errq [0:2][0:1023];
  reg [7:0] lostq [0:2][0:255];
  integer rxh [0:2], rxt [0:2], eh [0:2], et [0:2], lh [0:2], lt [0:2], done_cnt [0:2];
  reg [2:0] had_lost = 0, had_tx_error = 0;
  integer lost_in_frame = 0;
  genvar g;
  generate
    for (g = 0; g < 3; g = g + 1) begin : node
      reg [8:0] tec_before = 0;
      reg [7:0] rec_before = 0;
      reg [1:0] mode_before = 0;
      can_node #(.TSEG1(TSEG1), .TSEG2(TSEG2), .SJW(SJW), .MUTATION(MUTATION)) u (
        .clk(clk[g]), .rst_n(rstn[g]), .can_rx(rxi[g]), .can_tx(txo[g]),
        .tx_valid(tx_valid[g]), .tx_ready(tx_ready[g]), .tx_id(tx_word[g][79:69]), .tx_rtr(tx_word[g][68]),
        .tx_dlc(tx_word[g][67:64]), .tx_data(tx_word[g][63:0]), .tx_done(tx_done[g]),
        .rx_valid(rx_valid[g]), .rx_id(rx_id[g]), .rx_rtr(rx_rtr[g]), .rx_dlc(rx_dlc[g]), .rx_data(rx_data[g]),
        .err_valid(err_valid[g]), .err_code(err_code[g]), .arb_lost(arb_lost[g]), .sync_kind(sync_kind[g]),
        .tec(tec[g]), .rec(rec[g]), .mode(mode[g]));
      initial begin
        rh[g] = 0; rt[g] = 0; rxh[g] = 0; rxt[g] = 0; eh[g] = 0; et[g] = 0; lh[g] = 0; lt[g] = 0; done_cnt[g] = 0;
        tx_word[g] = 0;
      end
      // One request at a time; it stays up until the node takes it.
      always @(posedge clk[g]) begin
        if (!rstn[g]) tx_valid[g] <= 1'b0;
        else if (tx_valid[g] && tx_ready[g]) begin
          tx_valid[g] <= 1'b0;
          rh[g] <= (rh[g] + 1) % 64;
        end else if (!tx_valid[g] && rh[g] != rt[g]) begin
          tx_valid[g] <= 1'b1;
          tx_word[g] <= reqq[g][rh[g]];
        end
        // Everything the node reports, in order. Values are those before this clock edge.
        if (rstn[g]) begin
        if ((^{txo[g], tx_ready[g], tx_done[g], rx_valid[g], err_valid[g], arb_lost[g]}) === 1'bx) fail("CAN_UNKNOWN");
        if (tx_valid[g] && !tx_ready[g]) goal[35] = 1;
        if (rx_valid[g]) begin
          if ((^{rx_id[g], rx_rtr[g], rx_dlc[g], rx_data[g]}) === 1'bx) fail("CAN_UNKNOWN");
          rxq[g][rxt[g]] = {rx_id[g], rx_rtr[g], rx_dlc[g], rx_data[g]};
          rxt[g] = (rxt[g] + 1) % 256; frames = frames + 1;
          if (!rx_rtr[g] && rx_dlc[g] == 0) goal[0] = 1;
          if (!rx_rtr[g] && rx_dlc[g] == 8) goal[1] = 1;
          if (!rx_rtr[g] && rx_dlc[g] > 8) goal[2] = 1;
          if (rx_rtr[g]) goal[3] = 1;
        end
        if (arb_lost[g]) begin
          lostq[g][lt[g]] = u.n - 8'd1; lt[g] = (lt[g] + 1) % 256;
          if (u.n - 8'd1 <= 8'd11) goal[8] = 1; else goal[9] = 1;
          lost_in_frame = lost_in_frame + 1;
          if (lost_in_frame >= 2) goal[10] = 1;
          had_lost[g] = 1;
        end
        if (err_valid[g]) begin
          errq[g][et[g]] = err_code[g]; et[g] = (et[g] + 1) % 1024; errors = errors + 1;
          last_ok = 0; lost_in_frame = 0;
          goal[11 + err_code[g]] = 1;                       // 12 bit ... 17 overload
          if (err_code[g] == 3'd1 && u.state == 4'd10) goal[18] = 1;
          if (err_code[g] == 3'd2 && u.role_tx) goal[19] = 1;
          if (err_code[g] != 3'd6 && u.role_tx) had_tx_error[g] = 1;
          if (err_code[g] == 3'd5 && mode_before == 2'd1 && tec[g] == tec_before) goal[30] = 1;
        end
        if (tx_done[g]) begin
          done_cnt[g] = done_cnt[g] + 1; done_total = done_total + 1;
          last_ok = 1; lost_in_frame = 0;
          if (had_lost[g]) goal[11] = 1;
          if (had_tx_error[g]) goal[20] = 1;
          had_lost[g] = 0; had_tx_error[g] = 0;
        end
        if (sync_kind[g] != 2'd0) goal[31 + sync_kind[g]] = 1;      // 32 hard, 33 lengthened, 34 shortened
        // A node does not stretch its bit on the late edge of its own dominant level.
        if (sync_kind[g] == 2'd2 && txo[g] === 1'b0) fail("CAN_SYNC");
        // Where a start of frame may come, the edge restarts the bit instead of moving it by the jump width.
        if (sync_kind[g] >= 2'd2 && (u.state == 4'd1 || u.state == 4'd9 || (u.state == 4'd8 && u.cnt == 4'd2)))
          fail("CAN_SYNC");
        // Once per bit, with the values before this sample: states, and counter steps since the last sample.
        if (u.sample_now) begin
          if ((^{tec[g], rec[g], mode[g]}) === 1'bx) fail("CAN_UNKNOWN");
          if (u.state == 4'd2 && u.rx_stuff && u.fault == 3'd0) begin
            if (u.v) goal[5] = 1; else goal[4] = 1;
          end
          if (u.state == 4'd3) goal[6] = 1;
          if (mode[g] == 2'd1) goal[21] = 1;
          if (u.state == 4'd10 && u.flag_kind == 2'd1) goal[22] = 1;
          if (u.state == 4'd9) goal[23] = 1;
          if (mode[g] == 2'd2) goal[24] = 1;
          if (mode_before == 2'd2 && mode[g] != 2'd2) goal[25] = 1;
          if (tec[g] + 9'd1 == tec_before && mode_before != 2'd2) goal[26] = 1;
          if (rec[g] + 8'd1 == rec_before && rec_before <= 8'd127) goal[27] = 1;
          if (rec_before > 8'd127 && rec[g] == 8'd127) goal[28] = 1;
          if (rec[g] == rec_before + 8'd8 && (u.state == 4'd11 || u.state == 4'd12)) goal[29] = 1;
          tec_before = tec[g]; rec_before = rec[g]; mode_before = mode[g];
        end
        end else begin
          tec_before = 0; rec_before = 0; mode_before = 0;
        end
      end
    end
  endgenerate

  task wait_bits(input integer count);
    repeat (count * NTQ) @(posedge mclk);
  endtask

  // Wait until a node has reported something, for at most this many bit times.
  task wait_event(input integer kind, input integer n, input integer want, input integer limit, output reg ok);
    integer waited;
    begin
      waited = 0; ok = 0;
      while (!ok && waited <= limit * NTQ) begin
        case (kind)
          0: ok = rxh[n] != rxt[n];
          1: ok = eh[n] != et[n];
          2: ok = done_cnt[n] >= want;
          default: ok = lh[n] != lt[n];
        endcase
        if (!ok) begin @(posedge mclk); waited = waited + 1; end
      end
    end
  endtask

  reg level, ok;
  integer count, tolerance, node_i, expected_done [0:2];
  string names [0:NGOALS-1];
  initial begin
    names[0] = "frame/dlc0"; names[1] = "frame/dlc8"; names[2] = "frame/dlc-over-8"; names[3] = "frame/remote";
    names[4] = "frame/stuff-dominant"; names[5] = "frame/stuff-recessive"; names[6] = "frame/tail-stuff";
    names[7] = "frame/back-to-back"; names[8] = "arb/lost-id"; names[9] = "arb/lost-rtr"; names[10] = "arb/three-way";
    names[11] = "arb/retransmit"; names[12] = "error/bit"; names[13] = "error/stuff"; names[14] = "error/crc";
    names[15] = "error/form"; names[16] = "error/ack"; names[17] = "error/overload"; names[18] = "error/bit-in-flag";
    names[19] = "error/stuff-in-arbitration"; names[20] = "error/retransmit"; names[21] = "state/error-passive";
    names[22] = "state/passive-flag"; names[23] = "state/suspend"; names[24] = "state/bus-off"; names[25] = "state/recover";
    names[26] = "count/tx-decrement"; names[27] = "count/rx-decrement"; names[28] = "count/rx-clamp";
    names[29] = "count/rx-plus8"; names[30] = "count/ack-hold"; names[31] = "host/ready-idle";
    names[32] = "timing/hard-sync"; names[33] = "timing/lengthen"; names[34] = "timing/shorten";
    names[35] = "host/request-while-busy";
    if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "missing run arguments");
    $dumpfile(wave);
    // The bus, the three drivers and views, the disturbances and what each node reports; no clocks.
    $dumpvars(0, bus, txo, rxi, rstn, force_dom, view_dom, view_rec, tx_valid, tx_ready, tx_done, rx_valid, err_valid, arb_lost);
    fd = $fopen(vectors, "r");
    if (!fd) $fatal(1, "cannot open vectors");
    for (i = 0; i < 3; i = i + 1) expected_done[i] = 0;
    while (!$feof(fd)) begin
      fields = $fscanf(fd, "%h %h %h %h %h %h\n", op, fa, fb, fc, fd_, fe);
      if (fields != 6) $fatal(1, "bad vector row");
      node_i = fa[1:0];
      case (op)
        OP_RESET: begin
          rstn = 3'b000; wait_bits(2);
          for (i = 0; i < 3; i = i + 1) begin
            if (txo[i] !== 1'b1 || tx_ready[i] !== 1'b1 || tec[i] !== 9'd0 || rec[i] !== 8'd0 || mode[i] !== 2'd0 ||
                tx_done[i] !== 1'b0 || rx_valid[i] !== 1'b0 || err_valid[i] !== 1'b0) fail("CAN_RESET");
          end
          rstn = 3'b111; wait_bits(16);
        end
        OP_NODE: rstn[node_i] = fb[0];
        OP_WAIT: wait_bits(fa);
        OP_START: begin
          if (bus !== 1'b1) fail("CAN_END");
          started = 0; acc_valid = 0; qh = 0; qt = 0; inj_n = 0; inj_lo = 0; last_ok = 0;
          for (i = 0; i < 3; i = i + 1) begin
            done_cnt[i] = 0; expected_done[i] = 0;
            if (tx_ready[i] && !tx_valid[i]) goal[31] = 1;
          end
        end
        OP_INJ: begin
          inj_kind[inj_n] = fa[1:0]; inj_node[inj_n] = fb[1:0]; inj_start[inj_n] = fc; inj_len[inj_n] = fd_;
          inj_n = inj_n + 1;
        end
        OP_TXREQ: begin
          reqq[node_i][rt[node_i]] = {fb[10:0], fc[0], fd_[3:0], fe};
          rt[node_i] = (rt[node_i] + 1) % 64;
        end
        OP_RUN: begin
          next_run(level, count);
          tolerance = fb >> 5;
          if (level !== fa[0] || count < fb - tolerance || count > fb + tolerance) begin
            $display("run level=%b count=%0d expected level=%b count=%0d", level, count, fa[0], fb);
            fail("CAN_RUN");
          end
          runs_checked = runs_checked + 1;
        end
        OP_RX: begin
          wait_event(0, node_i, 0, 40, ok);
          if (!ok || rxq[node_i][rxh[node_i]] !== {fb[10:0], fc[0], fd_[3:0], fe}) fail("CAN_RX");
          rxh[node_i] = (rxh[node_i] + 1) % 256;
        end
        OP_ERR: begin
          wait_event(1, node_i, 0, 40, ok);
          if (!ok || errq[node_i][eh[node_i]] !== fb[2:0]) fail("CAN_ERR");
          eh[node_i] = (eh[node_i] + 1) % 1024;
        end
        OP_LOST: begin
          wait_event(3, node_i, 0, 40, ok);
          if (!ok || lostq[node_i][lh[node_i]] !== fb[7:0]) fail("CAN_LOST");
          lh[node_i] = (lh[node_i] + 1) % 256;
        end
        OP_DONE: begin
          wait_event(2, node_i, fb, 40, ok);
          if (!ok) fail("CAN_DONE");
          expected_done[node_i] = fb;
        end
        OP_END: begin
          wait_bits(fa);
          for (i = 0; i < 3; i = i + 1)
            if (rxh[i] != rxt[i] || eh[i] != et[i] || lh[i] != lt[i] || done_cnt[i] != expected_done[i] ||
                rh[i] != rt[i] || tx_valid[i] !== 1'b0) fail("CAN_END");
          if (qh != qt || (acc_valid && acc_level !== 1'b1) || bus !== 1'b1) fail("CAN_END");
        end
        OP_STATE: begin
          if (tec[node_i] !== fb[8:0] || rec[node_i] !== fc[7:0] || mode[node_i] !== fd_[1:0]) begin
            $display("node=%0d tec=%0d rec=%0d mode=%0d", node_i, tec[node_i], rec[node_i], mode[node_i]);
            fail("CAN_STATE");
          end
        end
        default: $fatal(1, "unknown operation");
      endcase
      checks = checks + 1;
    end
    for (k = 0; k < NGOALS; k = k + 1) if (goal[k]) $display("COVER %s", names[k]);
    $display("COUNT frames=%0d", frames);
    $display("COUNT errors=%0d", errors);
    $display("COUNT done=%0d", done_total);
    $display("COUNT runs=%0d", runs_checked);
    $display("RESULT PASS checks=%0d", checks);
    $finish;
  end
endmodule
