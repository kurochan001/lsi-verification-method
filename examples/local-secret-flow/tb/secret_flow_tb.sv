`timescale 1ns/1ps
// Two copies of secret_block get the same row of public inputs on every clock; only the
// written key differs (key0 for copy a, key1 for copy b).
//
// After each edge, two kinds of checks run, in this order:
//   SF_FLOW_*  the policy table: an output the table calls public must be the same in both
//              copies. This needs no expected value; it is the same check as the formal wrapper.
//   SF_*       each copy against the model in model.py, value by value.
// A flow check can only see a leak when the two secrets differ where the leak shows.
// Outputs are compared with !==, so an X where a value is specified is an error.
module secret_flow_tb;
    parameter MUTATION = 0, KW = 8;

    reg clk = 0;
    always #5 clk = ~clk;

    reg          rst_n = 0, lc = 0, key_we = 0, start = 0, zeroize = 0, dbg_req = 0, err_clr = 0;
    reg          scan_en = 0, scan_in = 0;
    reg [1:0]    dbg_addr = 0;
    reg [KW-1:0] key0 = 0, key1 = 0, din = 0;
    wire [3:0]    sta, stb;
    wire [KW-1:0] cta, ctb, rda, rdb;
    wire [KW+1:0] era, erb;
    wire          soa, sob;

    secret_block #(.KW(KW), .MUTATION(MUTATION)) a(
        .clk(clk), .rst_n(rst_n), .lc_in(lc), .key_we(key_we), .key_wdata(key0), .start(start), .din(din),
        .zeroize(zeroize), .dbg_req(dbg_req), .dbg_addr(dbg_addr), .err_clr(err_clr), .scan_en(scan_en),
        .scan_in(scan_in), .status(sta), .ct(cta), .dbg_rdata(rda), .err_info(era), .scan_out(soa));
    secret_block #(.KW(KW), .MUTATION(MUTATION)) b(
        .clk(clk), .rst_n(rst_n), .lc_in(lc), .key_we(key_we), .key_wdata(key1), .start(start), .din(din),
        .zeroize(zeroize), .dbg_req(dbg_req), .dbg_addr(dbg_addr), .err_clr(err_clr), .scan_en(scan_en),
        .scan_in(scan_in), .status(stb), .ct(ctb), .dbg_rdata(rdb), .err_info(erb), .scan_out(sob));

    integer fd, n, checks = 0, shifts = 0;
    integer loads = 0, zeroizes = 0, denied = 0, results = 0;
    reg [31:0] v [0:22];
    reg failed = 0, started = 0, allow = 0, clean = 1, had_key = 0;
    reg pprod, pscan, pctv, pkv, live;
    reg [1:0] pcode;
    string vectors, wave;

    task fail(input string label);
        begin
            if (!failed) begin
                failed = 1;
                $display("CHECK_FAIL %s", label);
                $fatal(1, "row=%0d time=%0t", checks, $time);
            end
        end
    endtask

    task expect_copy(input [3:0] st, input [KW-1:0] ctv, input [KW-1:0] rd, input [KW+1:0] er, input so,
                     input integer base);
        begin
            if (st !== v[base][3:0]) fail("SF_STATUS");
            if (ctv !== v[base + 1][KW-1:0]) fail("SF_CT");
            if (rd !== v[base + 2][KW-1:0]) fail("SF_DBG");
            if (er !== v[base + 3][KW+1:0]) fail("SF_ERR");
            if (so !== v[base + 4][0]) fail("SF_SCAN");
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "missing +VECTORS");
        if ($value$plusargs("WAVE=%s", wave)) begin
            $dumpfile(wave);
            $dumpvars(0, secret_flow_tb);
        end
        fd = $fopen(vectors, "r");
        if (fd == 0) $fatal(1, "cannot open vectors");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12],
                        v[13], v[14], v[15], v[16], v[17], v[18], v[19], v[20], v[21], v[22]);
            if (n != 23) $fatal(1, "bad vector row");
            if (started) @(negedge clk);
            started = 1;
            rst_n = v[0][0]; lc = v[1][0]; key_we = v[2][0]; key0 = v[3][KW-1:0]; key1 = v[4][KW-1:0];
            start = v[5][0]; din = v[6][KW-1:0]; zeroize = v[7][0]; dbg_req = v[8][0]; dbg_addr = v[9][1:0];
            err_clr = v[10][0]; scan_en = v[11][0]; scan_in = v[12][0];
            // The public state before the edge, from copy a (the flow check makes b agree).
            pprod = sta[2] === 1'b1; pscan = sta[3] === 1'b1; pctv = sta[1] === 1'b1; pkv = sta[0] === 1'b1;
            pcode = era[KW+1:KW];
            live = rst_n && !zeroize;
            // Coverage of what the row asks for, before the edge.
            if (!rst_n) begin
                if (lc) $display("COVER lc/prod");
                else $display("COVER lc/dev");
                if (pkv) $display("COVER reset/with-key");
            end
            if (rst_n && zeroize) begin
                zeroizes = zeroizes + 1;
                if (pkv) $display("COVER erase/zeroize");
                if (pscan) $display("COVER erase/in-scan");
            end
            if (live && !scan_en && key_we) begin
                loads = loads + 1;
                $display("COVER key/load");
                if (key0 != key1) $display("COVER key/secrets-differ");
                if (start) $display("COVER key/write-beats-start");
            end
            if (live && !scan_en && !key_we && start) begin
                if (pkv) begin
                    results = results + 1;
                    $display("COVER op/result");
                end else begin
                    $display("COVER op/no-key");
                    if (had_key) $display("COVER op/no-key-after-erase");
                end
            end
            if (live && dbg_req && dbg_addr == 2'd0) $display("COVER dbg/status");
            if (live && dbg_req && dbg_addr == 2'd1 && pprod) begin
                denied = denied + 1;
                $display("COVER dbg/key-denied");
                if (err_clr) $display("COVER err/event-beats-clear");
            end
            if (live && scan_en && !pscan && pprod) begin
                $display("COVER scan/prod-entry");
                if (dbg_req) $display("COVER scan/prod-entry-read");
            end
            if (live && scan_en && pscan && pprod) $display("COVER scan/prod-shift");
            if (live && scan_en && (start || key_we)) $display("COVER scan/ignored-ops");
            if (live && !scan_en && pscan) $display("COVER scan/exit");
            if (live && scan_en && pscan && !pprod && clean && had_key) $display("COVER erase/dev-scan");
            // The policy table for the edge.
            allow = live && dbg_req && ((dbg_addr == 2'd1 && !pprod) || (dbg_addr == 2'd2 && pctv));
            if (!rst_n || zeroize || (scan_en && !pscan && pprod)) clean = 1;
            else if (key_we && !scan_en) clean = 0;
            if (!rst_n) had_key = 0;
            else if (live && key_we && !scan_en) had_key = 1;
            shifts = live && scan_en && (pscan || !pprod) ? shifts + 1 : 0;

            @(posedge clk);
            #1;
            // Flow: the table, between the two copies.
            if (sta !== stb) fail("SF_FLOW_STATUS");
            if (sta[2] && soa !== sob) fail("SF_FLOW_SCAN");
            if (!allow && rda !== rdb) fail("SF_FLOW_DBG");
            if (era !== erb) fail("SF_FLOW_ERR");
            if (!sta[1] && cta !== ctb) fail("SF_FLOW_CT");
            if (clean && (cta !== ctb || rda !== rdb || soa !== sob)) fail("SF_FLOW_ERASED");
            // Each copy against the model.
            expect_copy(sta, cta, rda, era, soa, 13);
            expect_copy(stb, ctb, rdb, erb, sob, 18);
            // Coverage of what came out.
            if (allow && !pprod && dbg_addr == 2'd1 && rda !== rdb) $display("COVER dbg/key-dev");
            if (allow && dbg_addr == 2'd2 && rda !== rdb) $display("COVER dbg/result");
            if (live && dbg_req && dbg_addr == 2'd3 && rda != 0) $display("COVER dbg/error");
            if (clean && had_key && allow && !pprod) $display("COVER erase/dev-read");
            if (!sta[2] && soa !== sob) $display("COVER scan/dev-differs");
            if (sta[2] && sta[3] && shifts == 2 * KW + 1) $display("COVER scan/through-chain");
            if (sta[1] && cta !== ctb) $display("COVER flow/result-differs");
            if (live && err_clr && pcode != 0 && era[KW+1:KW] == 0) $display("COVER err/clear");
            checks = checks + 1;
        end
        $fclose(fd);
        $display("COUNT loads=%0d", loads);
        $display("COUNT zeroizes=%0d", zeroizes);
        $display("COUNT denied=%0d", denied);
        $display("COUNT results=%0d", results);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
