`timescale 1ns/1ps
// Replays detector events at their own times, drives the digital inputs once per clock and
// compares every output with the reference just before the next inputs are applied.
module por_tb #(parameter STAGES = 2, WAIT = 4, CAL_TIMEOUT = 8, MUTATION = 0);
    localparam integer T = 4000;
    localparam integer SAMPLE = T / 2 - 100;

    reg clk = 1'b0;
    reg pwr_ok = 1'b0;
    reg [3:0] strap = 4'd0;
    reg cal_done = 1'b0;
    reg flag_clr = 1'b0;
    wire rst_n, cfg_load, cal_start, ready, init_fail, por_flag;
    wire [3:0] cfg;

    por_sequence #(.STAGES(STAGES), .WAIT(WAIT), .CAL_TIMEOUT(CAL_TIMEOUT), .MUTATION(MUTATION)) dut (
        .clk(clk), .pwr_ok(pwr_ok), .strap(strap), .cal_done(cal_done), .flag_clr(flag_clr),
        .rst_n(rst_n), .cfg_load(cfg_load), .cal_start(cal_start), .ready(ready),
        .init_fail(init_fail), .cfg(cfg), .por_flag(por_flag));

    string vectors, events, wave;
    integer phase, fd, efd, checks, falls, releases;
    integer event_time, event_value;
    reg [3:0] in_strap;
    reg in_done, in_clr;
    reg [9:0] expected, observed, previous;
    // Monitors that do not use the reference.
    time last_edge;
    integer edges_since_rise, edges_in_low;
    reg seen_rise, released, was_cleared;
    reg seen_load, seen_handshake;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "%s at %0t ns, clock %0d", label, $time, checks);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("EVENTS=%s", events) ||
            !$value$plusargs("WAVE=%s", wave) || !$value$plusargs("PHASE=%d", phase))
            $fatal(1, "missing run arguments");
        if (phase < T) $fatal(1, "the first clock must come at least one period after time zero");
        $dumpfile(wave);
        $dumpvars(0, por_tb);
        fd = $fopen(vectors, "r");
        efd = $fopen(events, "r");
        if (!fd || !efd) $fatal(1, "cannot open run files");
        checks = 0; falls = 0; releases = 0;
        last_edge = 0; edges_since_rise = 0; edges_in_low = 0;
        seen_rise = 1'b0; released = 1'b0; was_cleared = 1'b0; seen_load = 1'b0; seen_handshake = 1'b0;
        previous = 10'h010;
        fork
            begin : clocking_loop
                #(phase);
                forever begin clk = 1'b1; #(T / 2); clk = 1'b0; #(T / 2); end
            end
            begin : detector_events
                while ($fscanf(efd, "%d %d\n", event_time, event_value) == 2) begin
                    if (event_time <= $time) $fatal(1, "detector events are not in time order");
                    #(event_time - $time) pwr_ok = event_value[0];
                    if (!event_value[0]) falls = falls + 1;
                end
            end
            begin : stimulus
                #(phase - T / 2);
                while ($fscanf(fd, "%h %h %h %h\n", in_strap, in_done, in_clr, expected) == 4) begin
                    strap = in_strap; cal_done = in_done; flag_clr = in_clr;
                    #(T / 2 + SAMPLE);
                    compare();
                    #(T / 2 - SAMPLE);
                end
                if (!$feof(fd)) $fatal(1, "unreadable vector line");
                $display("COUNT falls=%0d", falls);
                $display("COUNT releases=%0d", releases);
                $display("RESULT PASS checks=%0d", checks);
                $finish;
            end
        join
    end

    task compare;
        begin
            observed = {rst_n, cfg_load, cal_start, ready, init_fail, por_flag, cfg};
            if (^observed === 1'bx) fail("POR_UNKNOWN");
            if (!rst_n) begin seen_load = 1'b0; seen_handshake = 1'b0; end
            if (cfg_load) seen_load = 1'b1;
            if ((cal_start && !seen_load) || (ready && !(seen_load && seen_handshake))) fail("POR_ORDER");
            if (observed !== expected) begin
                $display("observed %b expected %b", observed, expected);
                fail("POR_STATE");
            end
            // Scenes, taken from what the circuit showed.
            if (ready && !previous[6]) $display("COVER init/ready");
            if (init_fail && !previous[5]) $display("COVER init/timeout");
            if (init_fail && cal_done) $display("COVER init/late-done-ignored");
            if (rst_n && previous[9] && !cfg_load && !cal_start && !ready && !init_fail && cal_done)
                $display("COVER init/early-done-ignored");
            if (ready && strap != cfg) $display("COVER cfg/held");
            if (rst_n && !por_flag && previous[4]) begin
                $display("COVER flag/cleared");
                was_cleared = 1'b1;
            end
            if (!previous[9] && flag_clr) $display("COVER flag/clear-in-reset-ignored");
            if (por_flag && was_cleared) begin
                $display("COVER flag/set-again");
                was_cleared = 1'b0;
            end
            previous = observed;
            checks = checks + 1;
        end
    endtask

    // Values just before each clock: the handshake that the ready state must have seen.
    always @(posedge clk) begin
        last_edge = $time;
        if (pwr_ok) edges_since_rise = edges_since_rise + 1;
        else edges_in_low = edges_in_low + 1;
        if (cal_start && cal_done) begin
            seen_handshake = 1'b1;
            if (dut.u_ctrl.count == 8'd0) $display("COVER init/done-first-clock");
            if (dut.u_ctrl.count == CAL_TIMEOUT - 1) $display("COVER init/done-last-clock");
        end
    end

    // Release must happen on a clock, and not before STAGES clocks have seen the detector high.
    always @(posedge rst_n) begin
        if ($time != last_edge || edges_since_rise < STAGES) fail("POR_RELEASE");
        released = 1'b1;
        releases = releases + 1;
        $display("COVER release/synchronous");
    end

    always @(posedge pwr_ok) begin
        if (seen_rise) begin
            if (edges_in_low == 0) $display("COVER pulse/between-clocks");
            else $display("COVER pulse/across-clock");
        end
        seen_rise = 1'b1;
        released = 1'b0;
        edges_since_rise = 0;
    end

    // One nanosecond after the detector falls, everything must be back at its reset value,
    // however short the pulse is and whatever the clock is doing.
    always @(negedge pwr_ok) if (seen_rise) begin
        if (!released) $display("COVER release/aborted");
        else if (previous[6]) $display("COVER reset/in-ready");
        else if (previous[5]) $display("COVER reset/in-fail");
        else if (previous[7]) $display("COVER reset/in-cal");
        else if (previous[8]) $display("COVER reset/in-load");
        else $display("COVER reset/in-wait");
        edges_in_low = 0;
        seen_load = 1'b0;
        seen_handshake = 1'b0;
        #1;
        if ({rst_n, cfg_load, cal_start, ready, init_fail, por_flag, cfg} !== 10'h010 ||
            dut.u_sync.chain !== {STAGES{1'b0}} || dut.u_ctrl.state !== 3'd0 || dut.u_ctrl.count !== 8'd0)
            fail("POR_PARTIAL");
    end
endmodule
