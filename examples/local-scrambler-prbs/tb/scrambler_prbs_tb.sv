`timescale 1ns/1ps
// Vector-driven test bench for the four circuits. One row is one clock of all four:
//   rst_n | generator: tag enable load seed data zero | checker: tag valid data err locked count stuck
//         | scrambler: tag valid din dout | descrambler: tag valid din dout original
// data, err and dout are combinational and are compared before the clock edge; zero, locked,
// count and stuck are compared after it. The tags only select cover lines.
module scrambler_prbs_tb;
    parameter PN = 7, PTAP = 6, SN = 58, STAP = 39, W = 1, MUTATION = 0;
    localparam LOCK = 32, LOSS = 8, CW = 6;
    localparam [CW-1:0] COUNT_MAX = {CW{1'b1}};

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg gen_enable = 0, seed_load = 0;
    reg [PN-1:0] seed = 0;
    wire [W-1:0] gen_data;
    wire gen_zero;
    prbs_gen #(.N(PN), .TAP(PTAP), .W(W), .MUTATION(MUTATION)) gen(
        .clk(clk), .rst_n(rst_n), .enable(gen_enable), .seed_load(seed_load), .seed(seed),
        .data(gen_data), .zero(gen_zero));

    reg chk_valid = 0;
    reg [W-1:0] chk_data = 0;
    wire [W-1:0] chk_err;
    wire chk_locked, chk_stuck;
    wire [CW-1:0] chk_count;
    prbs_check #(.N(PN), .TAP(PTAP), .W(W), .LOCK(LOCK), .LOSS(LOSS), .CW(CW), .MUTATION(MUTATION)) chk(
        .clk(clk), .rst_n(rst_n), .valid(chk_valid), .data(chk_data), .err(chk_err),
        .locked(chk_locked), .count(chk_count), .stuck(chk_stuck));

    reg scr_valid = 0, dsc_valid = 0;
    reg [W-1:0] scr_din = 0, dsc_din = 0;
    wire [W-1:0] scr_dout, dsc_dout;
    ss_scrambler #(.N(SN), .TAP(STAP), .W(W), .MUTATION(MUTATION)) scr(
        .clk(clk), .rst_n(rst_n), .valid(scr_valid), .din(scr_din), .dout(scr_dout));
    ss_descrambler #(.N(SN), .TAP(STAP), .W(W), .MUTATION(MUTATION)) dsc(
        .clk(clk), .rst_n(rst_n), .valid(dsc_valid), .din(dsc_din), .dout(dsc_dout));

    reg [63:0] er, tg, ge, gl, gs, xg, xz, tc, cv, cd, xe, xl, xc, xs, ts, sv, sd, xo, td, dv, dd, xd, og;
    integer fd, rc, checks = 0, i;
    integer gen_words = 0, chk_flags = 0, scr_words = 0, dsc_wrong = 0, window_wrong = 0;
    reg was_zero = 0, was_locked = 0, lost_seen = 0, error_scene = 0;
    reg [CW-1:0] was_count = 0;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d gen=%h/%h zero=%b err=%h/%h locked=%b/%b count=%0d/%0d stuck=%b/%b scr=%h/%h dsc=%h/%h",
                   checks, gen_data, xg[W-1:0], gen_zero, chk_err, xe[W-1:0], chk_locked, xl[0],
                   chk_count, xc[CW-1:0], chk_stuck, xs[0], scr_dout, xo[W-1:0], dsc_dout, xd[W-1:0]);
        end
    endtask

    function integer ones(input [W-1:0] value);
        integer k;
        begin
            ones = 0;
            for (k = 0; k < W; k = k + 1) ones = ones + value[k];
        end
    endfunction

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "VECTORS required");
        if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, scrambler_prbs_tb); end
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        @(negedge clk);
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                         er, tg, ge, gl, gs, xg, xz, tc, cv, cd, xe, xl, xc, xs, ts, sv, sd, xo, td, dv, dd, xd, og);
            if (rc != 23) $fatal(1, "malformed vector");
            rst_n = er[0];
            gen_enable = ge[0]; seed_load = gl[0]; seed = gs[PN-1:0];
            chk_valid = cv[0]; chk_data = cd[W-1:0];
            scr_valid = sv[0]; scr_din = sd[W-1:0];
            dsc_valid = dv[0]; dsc_din = dd[W-1:0];
            #4;
            if (rst_n) begin
                if (gen_data !== xg[W-1:0]) fail("GEN_DATA");
                if (chk_err !== xe[W-1:0]) fail("CHK_ERR");
                if (scr_dout !== xo[W-1:0]) fail("SCR_DATA");
                if (dsc_dout !== xd[W-1:0]) fail("DSC_DATA");
                // Generator scenes.
                if (gen_enable && !seed_load) begin
                    gen_words = gen_words + 1;
                    if (gen_data != 0) $display("COVER gen/run");
                    if (was_zero && gen_data == 0) $display("COVER gen/all-zero-stays-zero");
                end
                if (!gen_enable && !seed_load && tg == 1) $display("COVER gen/hold");
                if (seed_load && gen_enable && tg == 2) $display("COVER gen/load-over-enable");
                if (seed_load && seed != 0 && was_zero) $display("COVER gen/leave-zero-by-load");
                // Scrambler scenes.
                if (scr_valid) begin
                    scr_words = scr_words + 1;
                    if (scr_din != 0) $display("COVER scr/run");
                    if (ts == 2 && scr_din == 0 && scr_dout != 0) $display("COVER scr/zero-data-is-scrambled");
                    if (ts == 3 && scr_din == 0 && scr_dout == 0) $display("COVER scr/lockup-by-data");
                    if (ts == 4 && scr_dout != 0) $display("COVER scr/leave-lockup");
                end else if (ts == 1) $display("COVER scr/hold");
                // Descrambler scenes.
                if (dsc_valid) begin
                    dsc_wrong = dsc_wrong + ones(dsc_dout ^ og[W-1:0]);
                    if (td == 1 && dsc_dout != og[W-1:0]) $display("COVER dsc/wrong-before-n-bits");
                    if (td == 2 && dsc_dout == og[W-1:0]) $display("COVER dsc/aligned-after-n-bits");
                    if (td == 3) begin
                        if (!error_scene) window_wrong = 0;
                        window_wrong = window_wrong + ones(dsc_dout ^ og[W-1:0]);
                    end
                    if (td == 4 && error_scene && window_wrong == 3 && dsc_dout == og[W-1:0])
                        $display("COVER dsc/one-error-becomes-three");
                    if (td == 5 && dsc_dout != og[W-1:0]) $display("COVER dsc/slip-disturbs");
                    if (td == 6 && dsc_dout == og[W-1:0]) $display("COVER dsc/slip-realigned");
                    error_scene = td == 3 || (td == 4 && error_scene);
                end else if (td == 7) $display("COVER dsc/hold");
                if (chk_valid) chk_flags = chk_flags + ones(chk_err);
            end
            @(posedge clk); #1;
            if (gen_zero !== xz[0]) fail("GEN_ZERO");
            if (chk_locked !== xl[0]) fail("CHK_LOCK");
            if (chk_count !== xc[CW-1:0]) fail("CHK_COUNT");
            if (chk_stuck !== xs[0]) fail("CHK_STUCK");
            if (!rst_n) begin
                if (was_locked) $display("COVER reset/while-locked");
                lost_seen = 0;
            end else begin
                if (gen_zero && seed_load) $display("COVER gen/zero-flag");
                // Checker scenes.
                if (chk_valid) begin
                    if (chk_locked && !was_locked && !lost_seen) $display("COVER chk/lock");
                    if (chk_locked && !was_locked && lost_seen) $display("COVER chk/lock-again");
                    if (was_locked && !chk_locked && !chk_stuck) begin
                        $display("COVER chk/lock-lost-at-loss-flags");
                        lost_seen = 1;
                    end
                    if (tc == 2 && was_locked && chk_locked && xe[W-1:0] != 0) $display("COVER chk/single-error-keeps-lock");
                    if (tc == 3 && chk_locked && xe[W-1:0] == 0) $display("COVER chk/slip-realigned");
                    if (tc == 4 && chk_locked) $display("COVER chk/below-loss-keeps-lock");
                    if (tc == 5 && chk_stuck && !chk_locked) $display("COVER chk/stuck-zero-never-locks");
                    if (was_locked && xe[W-1:0] != 0 && chk_count == was_count + ones(xe[W-1:0]))
                        $display("COVER chk/count-while-locked");
                    if (!was_locked && !chk_locked && xe[W-1:0] != 0 && chk_count == was_count)
                        $display("COVER chk/no-count-while-unlocked");
                    if (was_count == COUNT_MAX && was_locked && xe[W-1:0] != 0 && chk_count == COUNT_MAX)
                        $display("COVER chk/count-saturates");
                end else if (tc == 1 && was_locked) $display("COVER chk/hold");
            end
            was_zero = gen_zero; was_locked = chk_locked; was_count = chk_count;
            checks = checks + 1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT gen_words=%0d", gen_words);
        $display("COUNT chk_flags=%0d", chk_flags);
        $display("COUNT scr_words=%0d", scr_words);
        $display("COUNT dsc_wrong=%0d", dsc_wrong);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
