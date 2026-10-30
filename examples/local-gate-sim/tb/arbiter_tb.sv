`timescale 1ns/1ps
// The same bench drives the RTL and the synthesized netlist. Each vector row is one cycle:
// inputs, then the outputs expected during that cycle. Outputs must never be X or Z.
module arbiter_tb;
    parameter GATE = 0, MUTATION = 0;
    reg clk = 0, rst_n = 0;
    reg [3:0] req = 0;
    wire out_valid, out_last;
    wire [1:0] out_id;
    wire [7:0] bursts;
    // The netlist has no parameters: synthesis already fixed MUTATION.
    generate if (GATE) begin : g_gate
        burst_arbiter dut(.*);
    end else begin : g_rtl
        burst_arbiter #(.MUTATION(MUTATION)) dut(.*);
    end endgenerate
    always #5 clk = ~clk;
    integer fd, n, checks = 0, started = 0, finished = 0, idle = 0, gap = 0;
    reg [15:0] v[0:5];
    reg [3:0] prev_req = 0, ids = 0;
    reg prev_valid = 0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label);
              $fatal(1, "cycle=%0d valid=%b last=%b id=%b bursts=%b", checks, out_valid, out_last, out_id, bursts); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave); $dumpvars(0, arbiter_tb);
        $display("VIEW %s", GATE ? "gate" : "rtl");
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5]);
            if (n != 6) $fatal(1, "bad row");
            if (!v[0][0] && rst_n && out_valid) $display("COVER reset/mid-burst");
            rst_n = v[0][0]; req = v[1];
            #1;
            if ((^{out_valid, out_last, out_id, bursts}) === 1'bx) fail("ARB_X");
            if (out_valid !== v[2][0] || out_last !== v[3][0]) fail("ARB_CONTROL");
            if ((out_valid && out_id !== v[4][1:0]) || bursts !== v[5][7:0]) fail("ARB_DATA");
            checks = checks + 1;
            if (rst_n) begin
                // A burst starts the cycle after its arbitration, so prev_req is what was arbitrated.
                if (out_valid && !prev_valid) begin
                    started = started + 1; ids[out_id] = 1;
                    if (&ids) $display("COVER grant/every-id");
                    case (prev_req)
                        4'b0001, 4'b0010, 4'b0100, 4'b1000: $display("COVER conflict/single");
                        4'b1111: $display("COVER conflict/all-four");
                        default: $display("COVER conflict/several");
                    endcase
                    if (prev_req[0] && prev_req[3]) $display("COVER conflict/lowest-and-highest");
                    if (gap == 2) $display("COVER flow/back-to-back");
                end
                if (out_last) begin
                    finished = finished + 1;
                    if (bursts == 8'hff) $display("COVER count/wrap");
                end
                idle = !out_valid && req == 0 ? idle + 1 : 0;
                if (idle == 3) $display("COVER flow/idle");
                gap = out_valid ? 0 : gap + 1;
            end else begin
                gap = 0; idle = 0;
            end
            prev_valid = out_valid; prev_req = req;
            @(negedge clk);
        end
        $display("COUNT bursts=%0d", started);
        $display("COUNT completed=%0d", finished);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
