`timescale 1ns/1ps
// Drives the self-test from vector rows and checks what an observer would see. Each row is one
// clock: [check, view, rst_n, start, fault, busy, done, pass, lfsr, response, signature].
// view 0 is the chip view: only busy, done and pass are compared, as on an FPGA with three LEDs.
// view 1 is the full view: the stimulus, the response stream and the signature are compared too.
// The same bench runs the RTL and the netlist that Yosys synthesizes (NETLIST=1).
module selftest_tb;
    parameter NETLIST = 0, PATTERNS = 64, SEED = 16'hace1, GOLDEN = 0, MUTATION = 0;
    reg clk = 0, rst_n = 0, start = 0;
    reg [8:0] fault_xor = 0;
    wire busy, done, pass;
    wire [15:0] lfsr, signature;
    wire [8:0] response;
    generate if (NETLIST) begin : g_netlist
        selftest_harness dut(.*);                // synthesis fixed the parameters
    end else begin : g_rtl
        selftest_harness #(.PATTERNS(PATTERNS), .SEED(SEED), .GOLDEN(GOLDEN), .MUTATION(MUTATION)) dut(.*);
    end endgenerate
    always #5 clk = ~clk;

    integer fd, n, checks = 0, runs = 0, passes = 0;
    reg [15:0] v[0:10];
    reg prev_done = 0, prev_busy = 0, faulted = 0;
    string vectors, wave;
    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d busy=%b done=%b pass=%b lfsr=%h response=%h signature=%h",
                   checks, busy, done, pass, lfsr, response, signature);
        end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, selftest_tb);
        $display("VIEW %s", NETLIST ? "netlist" : "rtl");
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
            if (n != 11) $fatal(1, "bad row");
            rst_n = v[2][0];
            start = v[3][0];
            fault_xor = v[4][8:0];
            #1;
            if (v[0][0]) begin
                // What a chip shows: the three result bits, never unknown.
                if ((^{busy, done, pass}) === 1'bx) fail("ST_X");
                if (busy !== v[5][0] || done !== v[6][0]) fail("ST_DONE");
                if (pass !== v[7][0]) fail("ST_PASS");
                if (v[1][0]) begin
                    if ((^{lfsr, response, signature}) === 1'bx) fail("ST_X");
                    if (lfsr !== v[8]) fail("ST_STIMULUS");
                    if (response !== v[9][8:0]) fail("ST_RESPONSE");
                    if (signature !== v[10]) fail("ST_SIGNATURE");
                    $display("COVER view/full");
                end else begin
                    $display("COVER view/chip");
                end
                if (busy) begin
                    case ({lfsr[12], lfsr[3]})
                        2'd0: $display("COVER stimulus/op-add");
                        2'd1: $display("COVER stimulus/op-sub");
                        2'd2: $display("COVER stimulus/op-and");
                        default: $display("COVER stimulus/op-xor");
                    endcase
                    if (response[8]) $display("COVER response/carry");
                    if (signature[15]) $display("COVER signature/feedback");
                    if (start) $display("COVER run/start-ignored");
                    if (!rst_n) $display("COVER reset/mid-run");
                    if (fault_xor != 0) faulted = 1;
                end else if (done && !rst_n) $display("COVER reset/after-done");
                else if (done && start) $display("COVER run/restart");
                if (done && !prev_done && prev_busy) begin
                    runs = runs + 1;
                    if (pass) begin
                        passes = passes + 1;
                        $display("COVER run/pass");
                    end else if (faulted) $display("COVER run/fail-on-fault");
                    faulted = 0;
                end
                prev_done = done;
                prev_busy = busy;
            end
            if (!rst_n) faulted = 0;
            @(posedge clk);
            checks = checks + 1;
            @(negedge clk);
        end
        $display("COUNT runs=%0d", runs);
        $display("COUNT passes=%0d", passes);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
