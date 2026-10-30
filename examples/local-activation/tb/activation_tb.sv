`timescale 1ns/1ps
module activation_tb;
    parameter FUNC=0, MUTATION=0;
    reg clk=0, rst_n=0, in_valid=0, out_ready=0;
    reg [11:0] in_x=0;
    wire in_ready, out_valid;
    wire [11:0] out_y;
    pwl_activation #(.FUNC(FUNC), .MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer fd, n, checks=0, accepted=0, completed=0, error, magnitude, worst=0;
    reg [31:0] v[0:7];
    reg [11:0] held_y, slot_x;
    reg held=0, last_accept=0;
    reg [63:0] positive_segments=0, negative_segments=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "cycle=%0d x=%0d y=%0d", checks, $signed(slot_x), $signed(out_y)); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave); $dumpvars(0, activation_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
            if (n != 8) $fatal(1, "bad row");
            if (!v[0][0] && rst_n && out_valid) $display("COVER reset/in-flight");
            rst_n = v[0][0]; in_valid = v[1][0]; in_x = v[2]; out_ready = v[3][0];
            #1;
            if (in_ready !== v[4][0] || out_valid !== v[5][0]) fail("ACT_CONTROL");
            if (rst_n && held && out_y !== held_y) fail("ACT_HOLD");
            // The expected value is the exact function scaled by 1024*256; the
            // tolerance is in 1/256 output LSB and arrives with each row.
            error = $signed(out_y) * 256 - $signed(v[6]);
            if (out_valid && (error > $signed(v[7]) || -error > $signed(v[7]))) fail("ACT_TOLERANCE");
            if (!rst_n) begin
                held = 0; last_accept = 0;
            end else begin
                if (out_valid && !out_ready) $display("COVER flow/stall");
                if (out_valid && out_ready) begin
                    completed = completed + 1;
                    if (error > worst) worst = error;
                    if (-error > worst) worst = -error;
                    magnitude = $signed(slot_x) < 0 ? -$signed(slot_x) : $signed(slot_x);
                    if (magnitude > 2047) magnitude = 2047;
                    if ($signed(slot_x) == -2048) $display("COVER input/min");
                    if ($signed(slot_x) == 2047) $display("COVER input/max");
                    if (slot_x == 0) $display("COVER input/zero");
                    if ($signed(slot_x) <= -1536) $display("COVER saturation/negative");
                    if ($signed(slot_x) >= 1536) $display("COVER saturation/positive");
                    if (magnitude % 32 == 0 && magnitude != 0) $display("COVER knot/exact");
                    if ($signed(slot_x) < 0) negative_segments[magnitude / 32] = 1;
                    else positive_segments[magnitude / 32] = 1;
                    if (&positive_segments) $display("COVER segment/all-positive");
                    if (&negative_segments) $display("COVER segment/all-negative");
                    if (error > 192 || -error > 192) $display("COVER error/above-0.75");
                    if (error > 0) $display("COVER error/positive");
                    if (error < 0) $display("COVER error/negative");
                end
                if (in_valid && in_ready) begin
                    accepted = accepted + 1; slot_x = in_x;
                    if (last_accept) $display("COVER flow/back-to-back");
                end
                last_accept = in_valid && in_ready;
                held = out_valid && !out_ready; held_y = out_y;
            end
            checks = checks + 1;
            @(posedge clk); #1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT completed=%0d", completed);
        $display("OBS max_error=%0d/256", worst);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
