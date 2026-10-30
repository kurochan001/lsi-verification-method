`timescale 1ns/1ps
// Each vector row is one cycle: inputs, then the in_ready, out_valid and result expected
// during that cycle. Operand classes are recorded at acceptance and credited when the
// result of that division has been checked.
module divider_tb;
    parameter W = 32, MUTATION = 0;
    localparam [W-1:0] MIN = {1'b1, {W-1{1'b0}}};
    reg clk = 0, rst_n = 0, flush = 0, in_valid = 0, in_signed = 0, out_ready = 0;
    reg [W-1:0] in_dividend = 0, in_divisor = 0;
    wire in_ready, out_valid;
    wire [W-1:0] out_quotient, out_remainder;
    divider #(.W(W), .MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer fd, n, checks = 0, accepted = 0, completed = 0, flushed = 0, age = 0;
    reg [63:0] v[0:10];
    reg [2*W-1:0] held_value;
    reg held = 0, pending = 0, normal = 0, last_done = 0, prev_valid = 0;
    reg [9:0] tag = 0;  // operand classes of the division in flight
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "cycle=%0d q=%h r=%h", checks, out_quotient, out_remainder); end
    endtask
    function [W-1:0] magnitude(input [W-1:0] x, input s);
        magnitude = s && x[W-1] ? -x : x;
    endfunction
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave); $dumpvars(0, divider_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
            if (n != 11) $fatal(1, "bad row");
            if (!v[0][0] && rst_n && pending) $display("COVER reset/in-flight");
            rst_n = v[0][0]; flush = v[1][0]; in_valid = v[2][0]; in_signed = v[3][0];
            in_dividend = v[4]; in_divisor = v[5]; out_ready = v[6][0];
            #1;
            if (in_ready !== v[7][0] || out_valid !== v[8][0]) fail("DIV_CONTROL");
            if (rst_n && held && {out_quotient, out_remainder} !== held_value) fail("DIV_HOLD");
            if (out_valid && {out_quotient, out_remainder} !== {v[9][W-1:0], v[10][W-1:0]}) fail("DIV_DATA");
            checks = checks + 1;
            if (!rst_n) begin
                held = 0; pending = 0; age = 0;
            end else begin
                if (pending) age = age + 1;  // cycles since acceptance
                if (out_valid && !prev_valid) begin
                    completed = completed + 1; pending = 0;
                    if (tag[0]) $display("COVER special/zero-signed");
                    if (tag[1]) $display("COVER special/zero-unsigned");
                    if (tag[2]) $display("COVER special/overflow");
                    if (tag[3]) $display("COVER short/smaller-magnitude");
                    if (tag[4]) $display("COVER normal/equal-magnitude");
                    if (tag[5]) $display("COVER sign/negative-dividend");
                    if (tag[6]) $display("COVER sign/negative-divisor");
                    if (tag[7]) $display("COVER sign/both-negative");
                    if (tag[8]) $display("COVER unsigned/top-bit");
                    if (tag[9]) $display("COVER operand/extreme");
                end
                if (out_valid && !out_ready && held) $display("COVER flow/held");
                if (flush && pending) begin
                    flushed = flushed + 1;
                    if (normal && age == W) $display("COVER flush/last-step");
                    else if (age > 0 && age < W && normal) $display("COVER flush/mid-division");
                    pending = 0;
                end
                if (flush && out_valid) $display("COVER flush/unread-result");
                if (in_valid && in_ready) begin
                    accepted = accepted + 1; pending = 1; age = 0;
                    if (last_done) $display("COVER flow/back-to-back");
                    normal = in_divisor != 0 && !(in_signed && in_dividend == MIN && &in_divisor) &&
                             magnitude(in_dividend, in_signed) >= magnitude(in_divisor, in_signed);
                    tag = 0;
                    tag[0] = in_signed && in_divisor == 0;
                    tag[1] = !in_signed && in_divisor == 0;
                    tag[2] = in_signed && in_dividend == MIN && &in_divisor;
                    tag[3] = in_divisor != 0 && magnitude(in_dividend, in_signed) < magnitude(in_divisor, in_signed);
                    tag[4] = normal && magnitude(in_dividend, in_signed) == magnitude(in_divisor, in_signed) &&
                             in_dividend != in_divisor;
                    tag[5] = normal && in_signed && in_dividend[W-1] && !in_divisor[W-1];
                    tag[6] = normal && in_signed && !in_dividend[W-1] && in_divisor[W-1];
                    tag[7] = normal && in_signed && in_dividend[W-1] && in_divisor[W-1];
                    tag[8] = normal && !in_signed && in_dividend[W-1] && in_divisor[W-1];
                    tag[9] = in_dividend == MIN || in_divisor == MIN || in_dividend == MIN - 1 || &in_dividend;
                end
            end
            held = rst_n && out_valid && !out_ready && !flush;
            held_value = {out_quotient, out_remainder};
            last_done = rst_n && out_valid && out_ready && !flush;
            prev_valid = out_valid;
            @(negedge clk);
        end
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT completed=%0d", completed);
        $display("COUNT flushed=%0d", flushed);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
