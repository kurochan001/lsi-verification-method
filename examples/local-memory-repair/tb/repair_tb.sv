`timescale 1ns/1ps
// The bench owns the physical memory and its stuck cells. It judges the repair by what the fuses
// say and by the cells the test after the repair touches, not by a copy of the allocation.
module repair_tb;
    parameter MUTATION = 0, ROWS = 4, COLS = 4, SR = 1, SC = 1;
    localparam PR = ROWS + SR, PC = COLS + SC, RB = $clog2(ROWS), CB = $clog2(COLS);
    localparam PRW = $clog2(PR), PCW = $clog2(PC), FW = 1 + SR * (RB + 1) + SC * (CB + 1);
    localparam ROW_BASE = 1, COL_BASE = 1 + SR * (RB + 1);

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, start = 0, req_ready = 0, fuse_blank = 0;
    wire ready, busy, done, repair_active, req_valid, req_write, req_data, fuse_prog;
    wire [1:0] status;
    wire [PRW-1:0] req_row;
    wire [PCW-1:0] req_col;
    wire [FW-1:0] fuse_q, fuse_d;

    // Physical memory: a stuck cell ignores what is written to it.
    reg mem [0:PR*PC-1];
    reg [127:0] stuck, stuck_value;
    integer cell_index;
    reg read_data;
    always @* begin
        cell_index = req_row * PC + req_col;
        read_data = stuck[cell_index] ? stuck_value[cell_index] : mem[cell_index];
    end

    mem_repair #(.MUTATION(MUTATION), .ROWS(ROWS), .COLS(COLS), .SR(SR), .SC(SC)) dut (
        .clk(clk), .rst_n(rst_n), .start(start), .ready(ready), .busy(busy), .done(done), .status(status),
        .repair_active(repair_active), .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write),
        .req_row(req_row), .req_col(req_col), .req_data(req_data), .read_data(read_data),
        .fuse_q(fuse_q), .fuse_prog(fuse_prog), .fuse_d(fuse_d));
    fuse_bank #(.WIDTH(FW)) fuses (.clk(clk), .blank(fuse_blank), .prog(fuse_prog), .d(fuse_d), .q(fuse_q));

    reg [127:0] v [0:7];
    string vectors, wave;
    integer fd, n, checks = 0, stall, operations, cycle, programs, r, c, k;
    integer clean = 0, repaired = 0, unrepairable = 0, retests = 0, late_faults = 0;
    reg [FW-1:0] fuse_before;
    reg [ROWS-1:0] row_repaired;
    reg [COLS-1:0] col_repaired;
    reg [SR-1:0] row_spare_bad, row_spare_used;
    reg [SC-1:0] col_spare_bad, col_spare_used;
    reg has_stuck0, has_stuck1, any_fault, placed;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d operations=%0d cycle=%0d status=%0d", checks, operations, cycle, status);
        end
    endtask

    // Once per cycle, with the outputs settled: no X, and fuses only ever gain bits.
    task sample;
        begin
            if (^{ready, busy, done, status, repair_active, req_valid, fuse_prog} === 1'bx) fail("REPAIR_X");
            if (req_valid && ^{req_write, req_row, req_col, req_data} === 1'bx) fail("REPAIR_X");
            if (^fuse_q === 1'bx || (fuse_before & ~fuse_q) != 0) fail("REPAIR_FUSE");
            if (fuse_prog) programs = programs + 1;
            fuse_before = fuse_q;
        end
    endtask

    task wait_ready;
        begin
            k = 0;
            while (!ready && k < 4) begin
                @(negedge clk);
                #1 sample;
                k = k + 1;
            end
            if (!ready || busy || done) fail("REPAIR_READY");
        end
    endtask

    // What the fuses say: repaired rows and columns, and the spares they use.
    task decode;
        begin
            row_repaired = 0; col_repaired = 0; row_spare_used = 0; col_spare_used = 0;
            for (k = 0; k < SR; k = k + 1)
                if (fuse_q[ROW_BASE + k * (RB + 1)]) begin
                    if (row_repaired[fuse_q[ROW_BASE + 1 + k * (RB + 1) +: RB]]) fail("REPAIR_FUSE");
                    row_spare_used[k] = 1;
                    row_repaired[fuse_q[ROW_BASE + 1 + k * (RB + 1) +: RB]] = 1;
                end
            for (k = 0; k < SC; k = k + 1)
                if (fuse_q[COL_BASE + k * (CB + 1)]) begin
                    if (col_repaired[fuse_q[COL_BASE + 1 + k * (CB + 1) +: CB]]) fail("REPAIR_FUSE");
                    col_spare_used[k] = 1;
                    col_repaired[fuse_q[COL_BASE + 1 + k * (CB + 1) +: CB]] = 1;
                end
        end
    endtask

    // One March test. With `remapped`, no access may touch a repaired row or column of the main array.
    task run_test(input integer stop_early, input integer remapped);
        begin
            operations = 0;
            cycle = 0;
            for (k = 0; k < PR * PC; k = k + 1) mem[k] = 1'bx;
            start = 1;
            @(posedge clk);
            #1;
            @(negedge clk);
            start = 0;
            #1 sample;
            if (!busy || done) fail("REPAIR_START");
            while (!done && cycle < 40 * PR * PC + (1 << ROWS) + 64) begin
                req_ready = stall == 0 || cycle % stall != 0;
                #1;
                if (req_valid && req_ready) begin
                    if (req_row >= PR || req_col >= PC) fail("REPAIR_RANGE");
                    if (remapped && ((req_row < ROWS && row_repaired[req_row]) || (req_col < COLS && col_repaired[req_col])))
                        fail("REPAIR_REMAP");
                    if (!req_write && read_data === 1'bx) fail("REPAIR_X");
                end
                @(posedge clk);
                if (req_valid && req_ready) begin
                    if (req_write) mem[cell_index] = req_data;
                    operations = operations + 1;
                end
                #1;
                @(negedge clk);
                #1 sample;
                cycle = cycle + 1;
                if (stop_early && operations >= 3) begin
                    if (!busy) fail("REPAIR_RESET");
                    rst_n = 0;
                    req_ready = 0;
                    @(negedge clk);
                    #1;
                    if (busy || done || ready || req_valid) fail("REPAIR_RESET");
                    rst_n = 1;
                    disable run_test;
                end
            end
            req_ready = 0;
            if (!done) fail("REPAIR_TIMEOUT");
            if (operations != 10 * (remapped ? ROWS * COLS : PR * PC)) fail("REPAIR_COUNT");
            @(negedge clk);
            #1 sample;
            if (!done || busy || req_valid) fail("REPAIR_DONE");
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, repair_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
            if (n != 8) $fatal(1, "bad row");
            stuck = v[0];
            stuck_value = v[1];
            stall = v[3];
            operations = 0;
            cycle = 0;
            programs = 0;

            // A blank device: fuses cleared before the reset is released.
            rst_n = 0;
            start = 0;
            req_ready = 0;
            fuse_blank = 1;
            repeat (2) @(negedge clk);
            fuse_blank = 0;
            fuse_before = 0;
            @(negedge clk);
            rst_n = 1;
            wait_ready;
            if (repair_active !== 1'b0) fail("REPAIR_LOAD");

            if (v[4]) begin
                run_test(1, 0);
                wait_ready;
                $display("COVER reset/mid-test");
            end
            run_test(0, 0);

            row_spare_bad = 0; col_spare_bad = 0; has_stuck0 = 0; has_stuck1 = 0; any_fault = stuck != 0;
            for (r = 0; r < PR; r = r + 1)
                for (c = 0; c < PC; c = c + 1)
                    if (stuck[r * PC + c]) begin
                        if (r >= ROWS) row_spare_bad[r - ROWS] = 1;
                        if (c >= COLS) col_spare_bad[c - COLS] = 1;
                        if (r < ROWS && c < COLS) begin
                            if (stuck_value[r * PC + c]) has_stuck1 = 1; else has_stuck0 = 1;
                        end
                    end

            case (v[5])
                0: begin
                    if (status !== 2'd0) fail("REPAIR_VERDICT");
                    if (fuse_q != 0 || programs != 0) fail("REPAIR_FUSE");
                    clean = clean + 1;
                    if (!any_fault) $display("COVER test/clean");
                    else $display("COVER spare/only-spare-faults");
                end
                2: begin
                    if (status !== 2'd2) fail("REPAIR_UNREPAIRABLE");
                    if (fuse_q != 0 || programs != 0) fail("REPAIR_FUSE");
                    unrepairable = unrepairable + 1;
                    if (v[7][1]) $display("COVER verdict/unrepairable-must");
                    else $display("COVER verdict/unrepairable-lines");
                end
                default: begin
                    if (status !== 2'd1) fail("REPAIR_VERDICT");
                    if (programs != 1 || fuse_q[0] !== 1'b1) fail("REPAIR_FUSE");
                    decode;
                    if ((row_spare_used & row_spare_bad) != 0 || (col_spare_used & col_spare_bad) != 0) fail("REPAIR_SPARE");
                    for (r = 0; r < ROWS; r = r + 1)
                        for (c = 0; c < COLS; c = c + 1)
                            if (stuck[r * PC + c] && !row_repaired[r] && !col_repaired[c]) fail("REPAIR_COVER");
                    repaired = repaired + 1;
                    $display("COVER fuse/programmed");
                    if (row_repaired != 0 && col_repaired == 0) $display("COVER alloc/row");
                    if (row_repaired == 0 && col_repaired != 0) $display("COVER alloc/column");
                    if (row_repaired != 0 && col_repaired != 0) $display("COVER alloc/row-and-column");
                    if (v[7][0]) $display("COVER alloc/must-repair");

                    // The fuses are read at reset only: a start before it must be ignored.
                    start = 1;
                    repeat (3) begin
                        @(negedge clk);
                        #1 sample;
                        if (busy || req_valid || status !== 2'd1) fail("REPAIR_REBOOT");
                    end
                    start = 0;
                    if (programs != 1) fail("REPAIR_FUSE");
                    $display("COVER reboot/required");

                    // A fault that appears after the repair, in a cell that no spare replaces.
                    if (v[2]) begin
                        placed = 0;
                        for (r = 0; r < ROWS; r = r + 1)
                            for (c = 0; c < COLS; c = c + 1)
                                if (!placed && !row_repaired[r] && !col_repaired[c] && !stuck[r * PC + c]) begin
                                    placed = 1;
                                    stuck[r * PC + c] = 1;
                                    stuck_value[r * PC + c] = 1;
                                end
                        if (!placed) $fatal(1, "no cell left for the late fault");
                        late_faults = late_faults + 1;
                    end

                    rst_n = 0;
                    @(negedge clk);
                    #1;
                    rst_n = 1;
                    wait_ready;
                    if (repair_active !== 1'b1) fail("REPAIR_LOAD");
                    $display("COVER reboot/remap-loaded");
                    run_test(0, 1);
                    if (status !== v[6][1:0]) fail("REPAIR_RETEST");
                    if (programs != 1) fail("REPAIR_FUSE");
                    retests = retests + 1;
                    if (v[2]) $display("COVER retest/late-fault");
                    else $display("COVER retest/pass");
                end
            endcase
            if (v[5] != 0 && has_stuck0) $display("COVER test/stuck0");
            if (v[5] != 0 && has_stuck1) $display("COVER test/stuck1");
            if (stall != 0) $display("COVER test/stall");
            if (row_spare_bad != 0 && v[5] != 0) $display("COVER spare/bad-row");
            if (col_spare_bad != 0 && v[5] != 0) $display("COVER spare/bad-column");
            checks = checks + 1;
        end
        $display("COUNT steps=%0d", checks);
        $display("COUNT clean=%0d", clean);
        $display("COUNT repaired=%0d", repaired);
        $display("COUNT unrepairable=%0d", unrepairable);
        $display("COUNT retests=%0d", retests);
        $display("COUNT late_faults=%0d", late_faults);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
