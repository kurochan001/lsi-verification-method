`timescale 1ns/1ps
module pll_guard_tb;
    parameter integer PLL_HALF = 17, PLL_PHASE = 2;
    parameter integer LOCK_CYCLES = 5, TIMEOUT = 24, MUTATION = 0;
    reg aon_clk = 0, pll_clk = 0;
    always #5 aon_clk = ~aon_clk;
    reg arst_n = 0, pll_locked = 0, clock_running = 0;
    wire clock_permit, clock_missing, work_reset_n;

    initial begin
        #(PLL_PHASE);
        forever begin
            #(PLL_HALF);
            // Park low only at a scheduled transition. Never cut a pulse short.
            pll_clk = (!pll_clk && clock_running);
        end
    end

    pll_guard #(.LOCK_CYCLES(LOCK_CYCLES), .TIMEOUT(TIMEOUT), .MUTATION(MUTATION)) dut(.*);

    string vectors, wave;
    integer fd, fields, checks = 0, slot;
    reg [31:0] row[0:7];
    reg [8:0] hits = 0;
    integer release_edges = 0;
    integer work_count = 0;
    time last_pll_edge;
    time last_release;

    task fail(input string label);
        $display("CHECK_FAIL %s", label);
        $fatal(1, "phase=%0d slot=%0d pll_period_ns=%0d lock=%b running=%b permit=%b reset_n=%b missing=%b work_edges=%0d",
            checks, slot, 2*PLL_HALF, pll_locked, clock_running, clock_permit,
            work_reset_n, clock_missing, work_count);
    endtask

    // A small workload observes real PLL edges, not the AON counter.
    always @(posedge pll_clk or negedge work_reset_n) begin
        if (!work_reset_n)
            work_count <= 0;
        else
            work_count <= work_count + 1;
    end

    always @(posedge pll_clk or negedge clock_permit) begin
        if (!clock_permit)
            release_edges <= 0;
        else
            release_edges <= release_edges + 1;
    end

    always @(posedge pll_clk) last_pll_edge <= $time;

    always @(posedge work_reset_n) begin
        last_release = $time;
        #0.001;
        if (last_pll_edge != last_release || release_edges != 2)
            fail("PLL_RESET_SYNC");
    end

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "missing arguments");
        $dumpfile(wave);
        $dumpvars(0, pll_guard_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        // Create a reset edge even when the operating clock is stopped.
        arst_n = 1;
        #1; arst_n = 0;
        while (!$feof(fd)) begin
            fields = $fscanf(fd, "%h %h %h %h %h %h %h %h\n",
                row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7]);
            if (fields != 8 || row[3] == 0) $fatal(1, "bad vector");
            @(negedge aon_clk);
            #0.001;
            {arst_n, pll_locked, clock_running} = {row[0][0], row[1][0], row[2][0]};
            for (slot = 0; slot < row[3]; slot = slot + 1) begin
                @(posedge aon_clk); #1;
                if (^{clock_permit, work_reset_n, clock_missing} === 1'bx)
                    fail("PLL_UNKNOWN");
                if (row[6][0] && {clock_permit, work_reset_n} !== 2'b00)
                    fail("PLL_LOCK_QUALIFY");
                if (work_reset_n === 0 && work_count !== 0) fail("PLL_WORK_RESET");
            end
            if (clock_missing !== row[5][0]) fail("PLL_WATCHDOG");
            if ({clock_permit, work_reset_n} !== {2{row[4][0]}}) begin
                if (!row[1][0]) fail("PLL_LOCK_LOSS");
                if (!row[2][0]) fail("PLL_STOPPED_RESET");
                fail("PLL_RESTART");
            end
            if (row[4][0] && work_count < 1) fail("PLL_WORK_RESET");
            hits = hits | row[7][8:0];
            checks = checks + 1;
        end
        if (hits[0]) $display("COVER lock/absent");
        if (hits[1]) $display("COVER lock/chatter");
        if (hits[2]) $display("COVER lock/acquired");
        if (hits[3]) $display("COVER lock/lost-running");
        if (hits[4]) $display("COVER lock/reacquired");
        if (hits[5]) $display("COVER clock/stopped-locked");
        if (hits[6]) $display("COVER clock/restarted");
        if (hits[7]) $display("COVER reset/while-stopped");
        if (hits[8]) $display("COVER reset/released-synchronously");
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
