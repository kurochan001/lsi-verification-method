`timescale 1ns/1ps
module conv_window_tb;
    parameter W=5, H=4, STRIDE=1, MUTATION=0;
    localparam PIXELS = W*H, OUT_W = (W-1)/STRIDE + 1;
    reg clk=0, rst_n=0, in_valid=0, out_ready=0;
    reg [7:0] in_pixel=0;
    wire in_ready, out_valid, out_last;
    wire [71:0] out_window;
    conv_window #(.W(W), .H(H), .STRIDE(STRIDE), .MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer fd, n, checks=0, accepted=0, windows=0, frames=0, received=0, index=0, done=0, r, c;
    reg [127:0] v[0:7];
    reg [72:0] held_value;
    reg held=0, last_pending=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "cycle=%0d window=%h last=%b", checks, out_window, out_last); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave); $dumpvars(0, conv_window_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
            if (n != 8) $fatal(1, "bad row");
            if (!v[0][0] && rst_n && (received != 0 && received != PIXELS)) $display("COVER reset/mid-frame");
            rst_n = v[0][0]; in_valid = v[1][0]; in_pixel = v[2]; out_ready = v[3][0];
            #1;
            if (in_ready !== v[4][0] || out_valid !== v[5][0]) fail("CONV_CONTROL");
            if (rst_n && held && {out_last, out_window} !== held_value) fail("CONV_HOLD");
            if (out_valid && {out_last, out_window} !== {v[7][0], v[6][71:0]}) fail("CONV_DATA");
            if (!rst_n) begin
                held = 0; received = 0; index = 0; done = 0; last_pending = 0;
            end else begin
                if (out_valid && !out_ready && received != PIXELS) $display("COVER stall/during-input");
                if (out_valid && !out_ready && received == PIXELS && last_pending) $display("COVER stall/during-flush");
                if (in_valid && !in_ready && received == PIXELS && !(out_valid && !out_ready))
                    $display("COVER input/blocked-by-flush");
                if (!in_valid && received != 0 && received != PIXELS) $display("COVER input/gap");
                if (in_valid && in_ready) begin
                    accepted = accepted + 1;
                    if (received == PIXELS) begin
                        if (last_pending) $display("COVER frame/overlap");
                        received = 0;
                    end
                    received = received + 1;
                    if (received == PIXELS) last_pending = 1;
                end
                if (out_valid && out_ready) begin
                    windows = windows + 1;
                    r = STRIDE * (index / OUT_W); c = STRIDE * (index % OUT_W);
                    if (r == 0 && c == 0) $display("COVER corner/top-left");
                    else if (r == 0 && c == W-1) $display("COVER corner/top-right");
                    else if (r == H-1 && c == 0) $display("COVER corner/bottom-left");
                    else if (r == H-1 && c == W-1) $display("COVER corner/bottom-right");
                    else if (r == 0) $display("COVER edge/top");
                    else if (r == H-1) $display("COVER edge/bottom");
                    else if (c == 0) $display("COVER edge/left");
                    else if (c == W-1) $display("COVER edge/right");
                    else $display("COVER interior");
                    if (done != 0) $display("COVER frame/second-since-reset");
                    if (out_last) begin
                        $display("COVER frame/last");
                        frames = frames + 1; done = done + 1; index = 0; last_pending = 0;
                    end else index = index + 1;
                end
                held = out_valid && !out_ready; held_value = {out_last, out_window};
            end
            checks = checks + 1;
            @(posedge clk); #1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT windows=%0d", windows);
        $display("COUNT frames=%0d", frames);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
