`timescale 1ns/1ps
// Vector-driven bench. A trial row gives the cycles of one run from a restart (or a power-on
// reset): which cycles carry a sample, the sample bits, and what the model in run.py expects -
// the sample after which ready rises, the samples at which each test fails, and the number of
// samples passed to the output. The bench checks every output on every cycle against those.
// A judge row checks the alarm counts of the statistic trials against an acceptance range.
module trng_tb;
    parameter W = 64, RCT_CUTOFF = 9, APT_CUTOFF = 40, STARTUP = 64, MUTATION = 0;
    localparam MAXC = 8192;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, restart = 0, in_valid = 0, in_bit = 0;
    wire out_valid, out_bit, ready, rct_fail, apt_fail, alarm;
    trng_health #(.W(W), .RCT_CUTOFF(RCT_CUTOFF), .APT_CUTOFF(APT_CUTOFF), .STARTUP(STARTUP),
                  .MUTATION(MUTATION)) dut (.*);

    reg [MAXC-1:0] vmask, dmask;
    reg [31:0] kind, n, er, ec, ea, eo, tag;
    integer fd, got, checks = 0, cycles = 0, c, k, j_prev, first_fail;
    integer trials = 0, samples = 0, outputs = 0, rct_alarms = 0, apt_alarms = 0;
    integer stat_trials = 0, stat_rct = 0, stat_apt = 0, trial_outputs;
    reg prev_acc, prev_bit, exp_out, prev_alarmed = 0, rct_seen, apt_seen, out_seen;
    // The bench's own view of the two tests, used for coverage only.
    integer run_len, run_val, wpos, wref, wcnt;
    reg run_gap;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d cycle=%0d", checks, c);
        end
    endtask

    // Outputs after k accepted samples; out_valid/out_bit belong to the previous cycle's sample.
    task check_outputs;
        begin
            if (^{out_valid, out_bit, ready, rct_fail, apt_fail, alarm} === 1'bx) fail("TRNG_UNKNOWN");
            if (ready !== (er != 0 && k >= er)) fail("TRNG_READY");
            if (rct_fail !== (ec != 0 && k >= ec)) fail("TRNG_RCT");
            if (apt_fail !== (ea != 0 && k >= ea)) fail("TRNG_APT");
            if (alarm !== (rct_fail | apt_fail)) fail("TRNG_ALARM");
            exp_out = prev_acc && er != 0 && j_prev > er && (first_fail == 0 || j_prev < first_fail);
            if (out_valid !== exp_out) fail("TRNG_OUTPUT");
            if (out_valid && out_bit !== prev_bit) fail("TRNG_DATA");
        end
    endtask

    task cover_cycle;
        begin
            if (rct_fail && !rct_seen) begin
                rct_seen = 1;
                $display("COVER rct/at-cutoff");
                $display("COVER rct/value%0d", run_val);
                if (run_gap) $display("COVER rct/gap-in-run");
            end
            if (apt_fail && !apt_seen) begin
                apt_seen = 1;
                $display("COVER apt/at-cutoff");
                $display("COVER apt/ref%0d", wref);
                if (wpos == 0) $display("COVER apt/last-in-window");
            end
            if (rct_fail && apt_fail) $display("COVER alarm/both");
            if (alarm && first_fail != 0 && k >= first_fail + RCT_CUTOFF) $display("COVER alarm/sticky");
            if (prev_acc && er != 0 && j_prev > er && first_fail != 0 && j_prev >= first_fail)
                $display("COVER output/suppressed");
            if (out_valid && !out_seen) begin
                out_seen = 1;
                $display("COVER output/first-after-startup");
            end
        end
    endtask

    task track_sample;
        begin
            if (in_valid) begin
                if (run_len > 0 && in_bit == run_val) begin
                    run_len = run_len + 1;
                end else begin
                    if (run_len == RCT_CUTOFF - 1 && !rct_fail) $display("COVER rct/below-cutoff");
                    run_val = in_bit;
                    run_len = 1;
                    run_gap = 0;
                end
                if (wpos == 0) begin
                    wref = in_bit;
                    wcnt = 1;
                end else if (in_bit == wref) begin
                    wcnt = wcnt + 1;
                end
                if (wpos == W - 1 && wcnt == APT_CUTOFF - 1 && !apt_fail) $display("COVER apt/below-cutoff");
                wpos = wpos == W - 1 ? 0 : wpos + 1;
            end else if (run_len > 0) begin
                run_gap = 1;
            end
        end
    endtask

    task run_trial;
        begin
            if (n > MAXC) $fatal(1, "trial longer than the bench holds");
            first_fail = (ec != 0 && (ea == 0 || ec < ea)) ? ec : ea;
            if (tag[7]) rst_n = 0;          // power-on reset instead of a restart
            else restart = 1;
            in_valid = 0;
            in_bit = 0;
            @(posedge clk);
            @(negedge clk);
            rst_n = 1;
            restart = 0;
            k = 0;
            j_prev = 0;
            prev_acc = 0;
            prev_bit = 0;
            trial_outputs = 0;
            rct_seen = 0;
            apt_seen = 0;
            out_seen = 0;
            run_len = 0;
            run_val = 0;
            run_gap = 0;
            wpos = 0;
            wref = 0;
            wcnt = 0;
            for (c = 0; c <= n; c = c + 1) begin
                if (c < n) begin
                    in_valid = vmask[c];
                    in_bit = dmask[c];
                end else begin
                    in_valid = 0;               // one more cycle shows the last sample's output
                    in_bit = 0;
                end
                #1;
                check_outputs;
                cover_cycle;
                if (out_valid) trial_outputs = trial_outputs + 1;
                track_sample;
                if (in_valid) k = k + 1;
                prev_acc = in_valid;
                prev_bit = in_bit;
                j_prev = k;
                cycles = cycles + 1;
                if (cycles == 4000) $dumpoff;   // long statistic runs keep only their start
                @(posedge clk);
                @(negedge clk);
            end
            if (run_len == RCT_CUTOFF - 1 && !rct_fail) $display("COVER rct/below-cutoff");
            if (trial_outputs != eo) fail("TRNG_OUTPUT");
            if (er != 0 && k >= er) begin
                $display("COVER startup/pass");
                if (prev_alarmed) $display("COVER reset/after-alarm");
                if (tag[7]) $display("COVER reset/power-on");
            end
            if (ec != 0 && ec <= STARTUP) $display("COVER startup/fail-rct");
            if (ea != 0 && ea <= STARTUP) $display("COVER startup/fail-apt");
            if (first_fail == STARTUP) $display("COVER startup/fail-last-sample");
            if (tag[0] && alarm) $display("COVER source/stuck-detected");
            if (tag[1] && alarm) $display("COVER source/biased-detected");
            if (tag[2] && !alarm && k >= 4 * W) $display("COVER source/alternating-passes");
            if (tag[4] && !alarm && er != 0 && k >= er) $display("COVER reset/clears-rct");
            if (tag[5] && !apt_fail) $display("COVER apt/window-restart");
            if (tag[6] && !alarm && er != 0 && k >= er) $display("COVER reset/clears-apt");
            if (tag[3]) begin
                stat_trials = stat_trials + 1;
                stat_rct = stat_rct + rct_fail;
                stat_apt = stat_apt + apt_fail;
            end
            trials = trials + 1;
            samples = samples + k;
            outputs = outputs + trial_outputs;
            rct_alarms = rct_alarms + rct_fail;
            apt_alarms = apt_alarms + apt_fail;
            prev_alarmed = alarm;
        end
    endtask

    // Judge row: n, vmask, dmask, er give the accepted range of RCT and APT alarms; ec the trials.
    task judge;
        begin
            $display("RATE trials=%0d rct=%0d apt=%0d", stat_trials, stat_rct, stat_apt);
            if (stat_trials != ec) fail("TRNG_RATE");
            if (stat_rct < n || stat_rct > vmask[31:0]) fail("TRNG_RATE");
            if (stat_apt < dmask[31:0] || stat_apt > er) fail("TRNG_RATE");
            $display("COVER rate/judged");
            stat_trials = 0;
            stat_rct = 0;
            stat_apt = 0;
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, trng_tb.dut);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "input missing");
        rst_n = 0;
        repeat (2) @(negedge clk);
        rst_n = 1;
        while (!$feof(fd)) begin
            got = $fscanf(fd, "%h %h %h %h %h %h %h %h %h\n", kind, n, vmask, dmask, er, ec, ea, eo, tag);
            if (got != 9) $fatal(1, "bad row");
            c = 0;
            if (kind == 1) run_trial;
            else if (kind == 2) judge;
            else $fatal(1, "bad row kind");
            checks = checks + 1;
        end
        $display("COUNT trials=%0d", trials);
        $display("COUNT samples=%0d", samples);
        $display("COUNT outputs=%0d", outputs);
        $display("COUNT rct_alarms=%0d", rct_alarms);
        $display("COUNT apt_alarms=%0d", apt_alarms);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
