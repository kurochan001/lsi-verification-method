`timescale 1ns/1ps
// Vector-driven test bench, one row per clock cycle:
//   rst_n req depth rate expected_grant expected_level tags
// The inputs are applied after the falling edge. The grant is a combinational answer to the
// request of the same cycle, so it is checked before the rising edge; the level is checked after it.
// Bit i of the tags names a goal (see TAGS in run.py); it is printed only for a row that passed.
module token_bucket_tb;
    parameter FRAC = 4, DEPTH_W = 4, RATE_W = 8, MUTATION = 0;
    localparam TW = DEPTH_W + FRAC;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, req = 0;
    reg [DEPTH_W-1:0] depth = 0;
    reg [RATE_W-1:0] rate = 0;
    wire grant;
    wire [TW-1:0] tokens;
    token_bucket #(.FRAC(FRAC), .DEPTH_W(DEPTH_W), .RATE_W(RATE_W), .MUTATION(MUTATION)) dut(.*);

    reg [31:0] er, eq, ed, ea, eg, el, et;
    integer fd, rc, checks = 0, grants = 0, k;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d req=%b depth=%0d rate=%0d grant=%b expected=%0d level=%0d expected=%0d",
                   checks, req, depth, rate, grant, eg, tokens, el);
        end
    endtask

    function string goal(input integer bit_index);
        case (bit_index)
            0: goal = "grant/exact-token";      1: goal = "deny/one-unit-short";
            2: goal = "deny/empty";             3: goal = "refill/saturate";
            4: goal = "refill/below-carry";     5: goal = "refill/carry";
            6: goal = "rate/zero";              7: goal = "rate/max";
            8: goal = "rate/fraction";          9: goal = "depth/zero";
            10: goal = "depth/max";             11: goal = "config/depth-down";
            12: goal = "config/rate-change";    13: goal = "reset/mid-run";
            14: goal = "window/tight";          15: goal = "burst/depth-then-deny";
            default: goal = "";
        endcase
    endfunction

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "VECTORS required");
        if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, token_bucket_tb); end
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        @(negedge clk);
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%h %h %h %h %h %h %h\n", er, eq, ed, ea, eg, el, et);
            if (rc != 7) $fatal(1, "malformed vector");
            if (et >= 32'h10000) $fatal(1, "unknown tag bit");
            rst_n = er[0]; req = eq[0]; depth = ed[DEPTH_W-1:0]; rate = ea[RATE_W-1:0];
            #1;
            if ((^{grant}) === 1'bx) fail("RL_UNKNOWN");
            if (rst_n && grant !== eg[0]) fail("RL_GRANT");
            if (grant && !req) fail("RL_GRANT");
            if (rst_n) grants = grants + grant;   // the answer of this cycle, before the edge
            @(posedge clk); #1;
            if ((^tokens) === 1'bx) fail("RL_UNKNOWN");
            if (tokens !== el[TW-1:0]) fail("RL_TOKENS");
            for (k = 0; k < 16; k = k + 1)
                if (et[k]) $display("COVER %s", goal(k));
            checks = checks + 1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT grants=%0d", grants);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
