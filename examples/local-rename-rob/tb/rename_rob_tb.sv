`timescale 1ns/1ps
// Applies one operation per row and compares what the design shows with the reference, which
// executed the same instructions one after another. Every cycle it also looks at the tables:
// the newest mapping, and where each physical register is.
module rename_rob_tb;
    parameter MUTATION = 0, LREGS = 4, PREGS = 10, ROB = 4;
    localparam DW = 8, LW = $clog2(LREGS), PW = $clog2(PREGS), RW = $clog2(ROB);
    localparam RESET = 0, ALLOC = 1, DONE = 2, FLUSH = 3, COMMIT = 4, READ = 5, BOTH = 6;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg alloc_valid = 0, done_valid = 0, done_exc = 0, flush_valid = 0, commit_en = 0;
    reg [LW-1:0] alloc_dst = 0, rd_addr = 0;
    reg [RW-1:0] done_tag = 0, flush_tag = 0;
    reg [DW-1:0] done_value = 0;
    wire alloc_ready, flush_ready, retire_valid, trap_valid, walking;
    wire [RW-1:0] alloc_tag, retire_tag, head_o;
    wire [LW-1:0] retire_dst;
    wire [DW-1:0] retire_value, rd_value;
    wire [RW:0] count;
    wire [PREGS-1:0] free_o;
    wire [LREGS*PW-1:0] rmap_o, cmap_o;
    wire [ROB*LW-1:0] rob_dst_o;
    wire [ROB*PW-1:0] rob_new_o, rob_old_o;

    rename_rob #(.MUTATION(MUTATION), .LREGS(LREGS), .PREGS(PREGS), .ROB(ROB), .DW(DW)) dut(
        .clk(clk), .rst_n(rst_n),
        .alloc_valid(alloc_valid), .alloc_dst(alloc_dst), .alloc_ready(alloc_ready), .alloc_tag(alloc_tag),
        .done_valid(done_valid), .done_tag(done_tag), .done_value(done_value), .done_exc(done_exc),
        .flush_valid(flush_valid), .flush_tag(flush_tag), .flush_ready(flush_ready),
        .commit_en(commit_en), .retire_valid(retire_valid), .trap_valid(trap_valid),
        .retire_tag(retire_tag), .retire_dst(retire_dst), .retire_value(retire_value),
        .rd_addr(rd_addr), .rd_value(rd_value), .walking(walking), .count(count),
        .free_o(free_o), .rmap_o(rmap_o), .cmap_o(cmap_o), .head_o(head_o),
        .rob_dst_o(rob_dst_o), .rob_new_o(rob_new_o), .rob_old_o(rob_old_o));

    integer fd, n, checks = 0, waited;
    integer allocs = 0, retires = 0, traps = 0, flushes = 0;
    reg [31:0] v [0:5];
    reg [RW-1:0] tag_of [0:4095];
    reg failed = 0;
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

    // One cycle: the inputs were set after the falling edge; they are removed after the next one.
    // Every operation ends with it, so that the next one starts on a falling edge again.
    task cycle;
        begin
            @(negedge clk);
            alloc_valid = 0; done_valid = 0; flush_valid = 0; commit_en = 0;
        end
    endtask

    task wait_idle;
        begin
            waited = 0;
            while (walking !== 1'b0) begin
                if (walking === 1'bx) fail("RR_X");
                if (waited > ROB + 4) fail("RR_WALK");
                waited = waited + 1;
                cycle;
            end
        end
    endtask

    // The tables, looked at in every cycle after the falling edge.
    integer l, a, p, places;
    reg [RW-1:0] slot;
    reg [PW-1:0] expect_map;
    reg twice, lost;
    always @(negedge clk) if (rst_n && !failed) begin
        if (^{free_o, rmap_o, cmap_o, head_o, count, walking} === 1'bx) fail("RR_X");
        // The newest mapping names the register of the youngest instruction that writes the
        // logical register, or the committed one.
        for (l = 0; l < LREGS; l = l + 1) begin
            expect_map = cmap_o[l*PW +: PW];
            for (a = 0; a < ROB; a = a + 1) begin
                slot = head_o + a[RW-1:0];
                if (a < count && rob_dst_o[slot*LW +: LW] == l) expect_map = rob_new_o[slot*PW +: PW];
            end
            if (rmap_o[l*PW +: PW] !== expect_map) fail("RR_RESTORE");
        end
        // Each physical register is free, mapped, or kept as an older mapping: exactly one of these.
        twice = 0; lost = 0;
        for (p = 0; p < PREGS; p = p + 1) begin
            places = free_o[p] ? 1 : 0;
            for (l = 0; l < LREGS; l = l + 1)
                if (rmap_o[l*PW +: PW] == p) places = places + 1;
            for (a = 0; a < ROB; a = a + 1) begin
                slot = head_o + a[RW-1:0];
                if (a < count && rob_old_o[slot*PW +: PW] == p) places = places + 1;
            end
            if (places > 1) twice = 1;
            if (places == 0) lost = 1;
        end
        // A register in two places is reported before a lost one: a wrong release causes both.
        if (twice) fail("RR_DOUBLE");
        if (lost) fail("RR_LEAK");
    end

    task check_retire(input integer ident, input [LW-1:0] dst, input [DW-1:0] value);
        begin
            if (trap_valid === 1'b1) fail("RR_TRAP");
            if (retire_valid !== 1'b1 || retire_tag !== tag_of[ident] || retire_dst !== dst) fail("RR_RETIRE");
            if (retire_value !== value) fail("RR_VALUE");
            retires = retires + 1;
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, rename_rob_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5]);
            if (n != 6) $fatal(1, "bad row");
            case (v[0])
                RESET: begin
                    rst_n = 0; cycle; cycle; rst_n = 1;
                    #1;
                    if (count !== 0 || walking !== 1'b0) fail("RR_RESET");
                    cycle;
                    if (v[5][6]) $display("COVER reset/in-flight");
                end
                ALLOC: begin
                    wait_idle;
                    alloc_valid = 1; alloc_dst = v[2][LW-1:0];
                    #1;
                    if (alloc_ready === 1'bx) fail("RR_X");
                    if (alloc_ready !== v[3][0]) fail("RR_READY");
                    if (alloc_ready) begin tag_of[v[1][11:0]] = alloc_tag; allocs = allocs + 1; end
                    cycle;
                    if (v[3][0]) $display("COVER alloc/accepted"); else $display("COVER stall/refused");
                    if (v[5][5]) $display("COVER reuse/after-flush");
                end
                DONE: begin
                    done_valid = 1; done_tag = tag_of[v[1][11:0]]; done_value = v[2][DW-1:0]; done_exc = v[3][0];
                    cycle;
                    if (v[5][0]) $display("COVER done/ignored");
                    else if (v[3][0]) $display("COVER done/exception"); else $display("COVER done/normal");
                end
                FLUSH: begin
                    wait_idle;
                    flush_valid = 1; flush_tag = tag_of[v[1][11:0]];
                    #1;
                    if (flush_ready !== 1'b1) fail("RR_FLUSH");
                    cycle;
                    wait_idle;
                    if (count !== v[2][RW:0]) fail("RR_FLUSH");
                    flushes = flushes + 1;
                    if (v[5][1]) $display("COVER flush/cancel");
                    if (v[5][2]) $display("COVER flush/nothing-younger");
                    if (v[5][3]) $display("COVER flush/same-dst");
                end
                COMMIT: begin
                    wait_idle;
                    commit_en = 1;
                    #1;
                    if (retire_valid === 1'bx || trap_valid === 1'bx) fail("RR_X");
                    case (v[1])
                        0: begin
                            if (retire_valid || trap_valid) fail("RR_RETIRE");
                            $display("COVER commit/not-done");
                        end
                        1: begin
                            check_retire(v[4], v[2][LW-1:0], v[3][DW-1:0]);
                            $display("COVER commit/retire");
                        end
                        default: begin
                            if (retire_valid === 1'b1 || trap_valid !== 1'b1) fail("RR_TRAP");
                            if (retire_tag !== tag_of[v[4][11:0]] || retire_dst !== v[2][LW-1:0]) fail("RR_TRAP");
                            traps = traps + 1;
                            $display("COVER commit/trap");
                            if (v[5][4]) $display("COVER trap/with-younger");
                        end
                    endcase
                    cycle;
                    if (v[1] == 2) begin
                        wait_idle;
                        if (count !== 0) fail("RR_TRAP");
                    end
                end
                READ: begin
                    rd_addr = v[1][LW-1:0];
                    #1;
                    if (^rd_value === 1'bx) fail("RR_X");
                    if (rd_value !== v[2][DW-1:0]) fail("RR_STATE");
                    cycle;
                    $display("COVER state/read");
                end
                BOTH: begin
                    wait_idle;
                    commit_en = 1; alloc_valid = 1; alloc_dst = v[2][LW-1:0];
                    #1;
                    check_retire(v[4][11:0], v[4][12 +: LW], v[5][DW-1:0]);
                    if (alloc_ready !== v[3][0]) fail("RR_READY");
                    if (alloc_ready) begin tag_of[v[1][11:0]] = alloc_tag; allocs = allocs + 1; end
                    cycle;
                    if (v[3][0]) $display("COVER commit/with-alloc"); else $display("COVER commit/with-refused-alloc");
                end
                default: $fatal(1, "unknown operation");
            endcase
            checks = checks + 1;
        end
        cycle;
        $display("COUNT steps=%0d", checks);
        $display("COUNT allocs=%0d", allocs);
        $display("COUNT retires=%0d", retires);
        $display("COUNT traps=%0d", traps);
        $display("COUNT flushes=%0d", flushes);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
