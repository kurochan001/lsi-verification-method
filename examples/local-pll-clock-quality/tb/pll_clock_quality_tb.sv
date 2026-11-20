`timescale 1ps/1ps
module pll_clock_quality_tb;
    parameter integer PERIOD_PS = 20000, MIN_PULSE_PS = 8000;
    parameter integer PERIOD_TOL_PS = 800, TIE_LIMIT_PS = 1000, STEP_LIMIT_PS = 1200;
    // The common runner sets this parameter for every top. Clock faults live in vectors.
    parameter integer MUTATION = 0;
    reg aon_clk = 0, pll_clk = 0, arst_n = 0, pll_locked = 0;
    always #5000 aon_clk = ~aon_clk;
    reg measure = 0;
    wire clock_permit, clock_missing, work_reset_n;
    pll_guard #(.MUTATION(MUTATION)) guard(.*);

    integer input_fd, trace_fd, fields, checks = 0, rises = 0, falls = 0, windows = 0;
    integer expected_window_edges = 0, observed_edges = 0;
    reg [31:0] low_ps, high_ps;
    reg lock_vector, window_vector;
    string vectors, wave;
    longint signed anchor = 0, last_rise = 0, last_fall = 0, previous_period = 0;
    longint signed now_ps, measured_period, pulse_ps, tie_ps, step_ps;
    reg high_at_rise = 0;
    reg high_at_limit = 0, low_at_limit = 0, period_at_limit = 0;
    reg tie_at_limit = 0, step_at_limit = 0, ignored_unlocked = 0;
    reg was_measuring = 0;

    function automatic longint signed abs_ps(input longint signed value);
        abs_ps = value >= 0 ? value : -value;
    endfunction

    task report_edge;
        $fdisplay(trace_fd, "%0d,%b,%b,%0d,%0d,%0d,%0d,%b,%b,%b",
            now_ps, pll_clk, measure, measured_period, pulse_ps, tie_ps, step_ps,
            pll_locked, clock_permit, work_reset_n);
    endtask

    task fail(input string label);
        $display("CHECK_FAIL %s", label);
        $fatal(1, "time_ps=%0d clock=%b window_edges=%0d nominal_ps=%0d period_ps=%0d pulse_ps=%0d tie_ps=%0d step_ps=%0d locked=%b permit=%b reset_n=%b",
            now_ps, pll_clk, rises, PERIOD_PS, measured_period, pulse_ps, tie_ps, step_ps,
            pll_locked, clock_permit, work_reset_n);
    endtask

    // No timing values from the stimulus enter this process. It observes real edges.
    always @(pll_clk) begin
        if (trace_fd != 0 && arst_n) begin
            observed_edges = observed_edges + 1;
            now_ps = $time;
            measured_period = 0;
            pulse_ps = 0;
            tie_ps = 0;
            step_ps = 0;
            if (pll_clk === 1'b1) begin
                high_at_rise = measure;
                if (measure) begin
                    if (!was_measuring) begin
                        windows = windows + 1;
                        anchor = now_ps;
                    end else begin
                        measured_period = now_ps - last_rise;
                        pulse_ps = now_ps - last_fall;
                        tie_ps = now_ps - (anchor + rises * longint'(PERIOD_PS));
                        if (rises >= 2)
                            step_ps = measured_period - previous_period;
                    end
                end
                report_edge();
                if (measure) begin
                    if ({pll_locked, clock_permit, work_reset_n, clock_missing} !== 4'b1110)
                        fail("PLL_WINDOW_STATE");
                    if (was_measuring) begin
                        if (pulse_ps < MIN_PULSE_PS) fail("PLL_SHORT_LOW");
                        if (abs_ps(measured_period - PERIOD_PS) > PERIOD_TOL_PS) fail("PLL_PERIOD");
                        if (abs_ps(tie_ps) > TIE_LIMIT_PS) fail("PLL_TIE");
                        if (rises >= 2 && abs_ps(step_ps) > STEP_LIMIT_PS) fail("PLL_CYCLE_STEP");
                        if (pulse_ps == MIN_PULSE_PS) low_at_limit = 1;
                        if (abs_ps(measured_period - PERIOD_PS) == PERIOD_TOL_PS) period_at_limit = 1;
                        if (abs_ps(tie_ps) == TIE_LIMIT_PS) tie_at_limit = 1;
                        if (abs_ps(step_ps) == STEP_LIMIT_PS) step_at_limit = 1;
                        previous_period = measured_period;
                    end
                    rises = rises + 1;
                end
                was_measuring = measure;
                last_rise = now_ps;
            end else if (pll_clk === 1'b0) begin
                pulse_ps = now_ps - last_rise;
                report_edge();
                if (high_at_rise) begin
                    if ({pll_locked, clock_permit, work_reset_n, clock_missing} !== 4'b1110)
                        fail("PLL_WINDOW_STATE");
                    if (pulse_ps < MIN_PULSE_PS) fail("PLL_SHORT_HIGH");
                    if (pulse_ps == MIN_PULSE_PS) high_at_limit = 1;
                    falls = falls + 1;
                end else if (pulse_ps < MIN_PULSE_PS && pll_locked === 1'b0) begin
                    if (work_reset_n !== 1'b0) fail("PLL_STARTUP_RESET");
                    ignored_unlocked = 1;
                end
                last_fall = now_ps;
            end else
                fail("PLL_EDGE_UNKNOWN");
        end
    end

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "missing run arguments");
        $dumpfile(wave);
        $dumpvars(0, pll_clock_quality_tb);
        input_fd = $fopen(vectors, "r");
        trace_fd = $fopen("clock_edges.csv", "w");
        if (!input_fd || !trace_fd) $fatal(1, "cannot open run files");
        $fdisplay(trace_fd, "time_ps,clock,window,period_ps,pulse_ps,tie_ps,step_ps,locked,permit,reset_n");
        arst_n = 1;
        #1; arst_n = 0;
        #20001; arst_n = 1;
        while (!$feof(input_fd)) begin
            fields = $fscanf(input_fd, "%h %h %h %h\n", low_ps, high_ps, lock_vector, window_vector);
            if (fields != 4 || ^{low_ps, high_ps, lock_vector, window_vector} === 1'bx ||
                low_ps <= 1 || high_ps == 0)
                $fatal(1, "bad clock vector");
            if (window_vector)
                expected_window_edges = expected_window_edges + 1;
            // Update the window off both edges. This 1 ps is included in the requested low width.
            #1;
            {pll_locked, measure} = {lock_vector, window_vector};
            #(low_ps - 1); pll_clk = 1;
            #(high_ps); pll_clk = 0;
            checks = checks + 1;
        end
        #1;
        if (windows != 1 || rises < 14 || falls != rises || rises != expected_window_edges ||
            observed_edges != 2*checks) fail("PLL_INCOMPLETE_TRACE");
        if (ignored_unlocked) $display("COVER window/ignored-unlocked");
        if (rises == falls) $display("COVER window/complete");
        if (high_at_limit) $display("COVER bounds/high");
        if (low_at_limit) $display("COVER bounds/low");
        if (period_at_limit) $display("COVER bounds/period");
        if (tie_at_limit) $display("COVER bounds/tie");
        if (step_at_limit) $display("COVER bounds/cycle-step");
        $fclose(input_fd);
        $fclose(trace_fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
