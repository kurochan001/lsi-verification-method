`timescale 1ns/1ps
// Vector-driven test bench. Each row holds the inputs of one cycle and the count and tick
// expected after its clock edge. The op column selects how a row shortens the test:
//   0 none   1 test load through the pins   2 force of count and of the carry flag
//   3 force of count alone (shown as a mistake)   4 test_load without test_mode (ignored)
// The force code is compiled only when METHOD is 2, because it names a signal that exists
// only when the carry chain is cut (WIDTH > SPLIT).
module long_counter_tb;
    parameter WIDTH = 32, SPLIT = 16, METHOD = 0, MUTATION = 0;
    localparam HALF = WIDTH / 2;
    localparam [WIDTH-1:0] ONE = 1;
    localparam [WIDTH-1:0] MAX = {WIDTH{1'b1}};
    localparam [WIDTH-1:0] TOP = ONE << (WIDTH - 1);
    localparam [HALF-1:0] HALF_MAX = {HALF{1'b1}};

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, enable = 0, clear = 0, test_mode = 0, test_load = 0;
    reg [WIDTH-1:0] limit = 0, test_value = 0;
    wire [WIDTH-1:0] count;
    wire tick;
    long_counter #(.WIDTH(WIDTH), .SPLIT(SPLIT), .MUTATION(MUTATION)) dut(.*);

    reg [1:0] force_kind = 0;        // 0 released, 1 count and carry flag, 2 count alone
    reg [WIDTH-1:0] force_value = 0;
    generate
        if (METHOD == 2) begin : g_force
            always @(force_kind) begin
                if (force_kind == 1) begin
                    force dut.count = force_value;
                    force dut.g_split.carry_q = &force_value[SPLIT-1:0];
                end else if (force_kind == 2) begin
                    force dut.count = force_value;
                end else begin
                    release dut.count;
                    release dut.g_split.carry_q;
                end
            end
        end
    endgenerate

    reg [63:0] er, ee, ec, eo, ev, el, ex, et;   // one row; values are at most 64 bits wide
    reg [WIDTH-1:0] pc;                         // count before the edge
    reg [WIDTH-1:0] seen = 0;                   // carries into each bit that were observed
    integer fd, rc, checks = 0, ticks = 0, jumps = 0, k;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "cycle=%0d op=%0d count=%h expected=%h tick=%b expected=%b",
                   checks, eo, count, ex[WIDTH-1:0], tick, et[0]);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "VECTORS required");
        if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, long_counter_tb); end
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        repeat (2) @(negedge clk);   // known reset before the first row
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%h %h %h %h %h %h %h %h\n", er, ee, ec, eo, ev, el, ex, et);
            if (rc != 8) $fatal(1, "malformed vector");
            if (eo > 4 || ((eo == 2 || eo == 3) && METHOD != 2)) $fatal(1, "operation not available");
            pc = count;
            rst_n = er[0]; enable = ee[0]; clear = ec[0]; limit = el[WIDTH-1:0];
            test_mode = eo == 1; test_load = eo == 1 || eo == 4;
            test_value = ev[WIDTH-1:0];
            force_value = ev[WIDTH-1:0];
            force_kind = eo == 2 ? 2'd1 : eo == 3 ? 2'd2 : 2'd0;
            @(posedge clk); #1;
            if (count !== ex[WIDTH-1:0])
                fail(eo == 1 || eo == 2 || eo == 3 ? "CNT_LOAD" : et[0] ? "CNT_WRAP" : "CNT_COUNT");
            if (tick !== et[0]) fail("CNT_TICK");
            force_kind = 0;
            ticks = ticks + tick;
            if (eo == 1 || eo == 2 || eo == 3) jumps = jumps + 1;
            if (!rst_n) begin
                if (pc != 0) $display("COVER reset/active");
            end else if (eo == 1) begin
                $display("COVER test/load");
                if (enable && pc == limit) $display("COVER test/load-over-enable");
            end else if (eo == 0 || eo == 4) begin
                if (eo == 4) $display("COVER test/load-ignored");
                if (clear && enable && pc != 0) $display("COVER count/clear-over-enable");
                if (clear && enable && pc == limit) $display("COVER count/clear-on-match");
                if (!clear && !enable && pc != 0) $display("COVER count/hold");
                if (!clear && !enable && pc[HALF-1:0] == HALF_MAX - 1'b1) $display("COVER pause/at-carry-minus-one");
                if (!clear && !enable && pc[HALF-1:0] == HALF_MAX) $display("COVER pause/at-carry");
                if (tick) begin
                    $display("COVER count/wrap-at-limit");
                    if (limit == 0) $display("COVER count/limit-zero");
                    if (limit == MAX) $display("COVER count/limit-max");
                end
                if (!clear && enable && !tick) begin
                    if (pc == MAX) $display("COVER count/rollover-without-tick");
                    if ((pc ^ limit) == TOP) $display("COVER match/top-bit-differs");
                    if (pc[HALF-1:0] == HALF_MAX) $display("COVER carry/half");
                    if (pc == TOP - 1'b1) $display("COVER carry/top");
                    for (k = 1; k < WIDTH; k = k + 1)
                        if (pc == (ONE << k) - 1'b1) seen[k] = 1;
                    if (seen[WIDTH-1:1] == MAX[WIDTH-1:1]) $display("COVER carry/every-bit");
                end
            end
            checks = checks + 1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT ticks=%0d", ticks);
        $display("COUNT jumps=%0d", jumps);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
