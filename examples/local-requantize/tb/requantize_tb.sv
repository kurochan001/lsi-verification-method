`timescale 1ns/1ps
module requantize_tb;
    parameter CH=2, ACT_MIN=-128, ACT_MAX=127, MUTATION=0;
    localparam CW = $clog2(CH);
    reg clk=0, rst_n=0, cfg_valid=0, in_valid=0, out_ready=0;
    reg [CW-1:0] cfg_ch=0, in_ch=0;
    reg [30:0] cfg_mult=0;
    reg [4:0] cfg_shift=0;
    reg [7:0] cfg_zp=0;
    reg [31:0] in_x=0;
    wire in_ready, out_valid, out_sat;
    wire [7:0] out_data;
    requantize #(.CH(CH), .ACT_MIN(ACT_MIN), .ACT_MAX(ACT_MAX), .MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer fd, n, i, checks=0, accepted=0, completed=0, writes=0, head=0, tail=0, inflight=0;
    reg [63:0] v[0:13];
    reg [8:0] held_value;
    reg held=0, last_accept=0;
    reg [30:0] tm[0:CH-1];
    reg [4:0] ts[0:CH-1];
    reg [7:0] tz[0:CH-1];
    reg [CH-1:0] written=0, channels=0;
    reg [31:0] shifts=0;
    reg [17:0] tag[0:15];  // rounding and parameter events of each accepted value
    reg [17:0] t;
    longint ab, high;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "cycle=%0d out=%h sat=%b", checks, out_data, out_sat); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave); $dumpvars(0, requantize_tb);
        for (i = 0; i < CH; i = i + 1) begin tm[i] = 0; ts[i] = 0; tz[i] = 0; end
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13]);
            if (n != 14) $fatal(1, "bad row");
            if (!v[0][0] && rst_n && inflight != 0) $display("COVER reset/in-flight");
            rst_n = v[0][0]; cfg_valid = v[1][0]; cfg_ch = v[2]; cfg_mult = v[3]; cfg_shift = v[4]; cfg_zp = v[5];
            in_valid = v[6][0]; in_ch = v[7]; in_x = v[8]; out_ready = v[9][0];
            #1;
            if (in_ready !== v[10][0] || out_valid !== v[11][0]) fail("REQ_CONTROL");
            if (rst_n && held && {out_sat, out_data} !== held_value) fail("REQ_HOLD");
            if (out_valid && {out_sat, out_data} !== {v[13][0], v[12][7:0]}) fail("REQ_DATA");
            if (!rst_n) begin
                held = 0; head = 0; tail = 0; inflight = 0; written = 0; last_accept = 0;
            end else begin
                if (out_valid && !out_ready && in_valid && in_ready) $display("COVER flow/accept-during-stall");
                if (in_valid && !in_ready) $display("COVER flow/input-blocked");
                if (out_valid && out_ready) begin
                    completed = completed + 1; inflight = inflight - 1;
                    t = tag[head]; head = (head + 1) % 16;
                    if (t[0]) $display("COVER srdhm/tie-positive");
                    if (t[1]) $display("COVER srdhm/tie-negative");
                    if (t[2]) $display("COVER rdbpot/tie-positive");
                    if (t[3]) $display("COVER rdbpot/tie-negative");
                    if (t[9]) $display("COVER zp/extreme");
                    if (t[10]) $display("COVER mult/max");
                    if (t[11]) $display("COVER mult/min");
                    if (t[12]) $display("COVER reset/params-cleared");
                    if (t[13]) $display("COVER param/write-same-edge");
                    if (t[14]) $display("COVER param/change-in-flight");
                    shifts[t[8:4]] = 1; channels[t[16:15]] = 1;
                    if (&shifts) $display("COVER shift/all-32");
                    if (&channels) $display("COVER channel/all");
                    if (out_sat && $signed(out_data) == ACT_MIN) $display("COVER clamp/low");
                    if (out_sat && $signed(out_data) == ACT_MAX) $display("COVER clamp/high");
                    if (!out_sat && ($signed(out_data) == ACT_MIN || $signed(out_data) == ACT_MAX))
                        $display("COVER clamp/at-limit");
                end
                if (cfg_valid)
                    for (i = head; i != tail; i = (i + 1) % 16)
                        if (tag[i][16:15] == cfg_ch) tag[i][14] = 1;
                if (in_valid && in_ready) begin
                    accepted = accepted + 1; inflight = inflight + 1;
                    if (last_accept) $display("COVER flow/back-to-back");
                    ab = $signed(in_x) * longint'(tm[in_ch]);
                    high = (ab + (ab >= 0 ? 64'sd1073741824 : -64'sd1073741823)) / 64'sd2147483648;
                    t = 0;
                    t[0] = ab[30:0] == 31'h40000000 && ab >= 0;
                    t[1] = ab[30:0] == 31'h40000000 && ab < 0;
                    if (ts[in_ch] != 0 && (high & ((64'sd1 <<< ts[in_ch]) - 1)) == (64'sd1 <<< (ts[in_ch] - 1))) begin
                        t[2] = high > 0; t[3] = high < 0;
                    end
                    t[8:4] = ts[in_ch];
                    t[9] = tz[in_ch] == 8'h80 || tz[in_ch] == 8'h7f;
                    t[10] = tm[in_ch] == 31'h7fffffff;
                    t[11] = tm[in_ch] == 31'h40000000;
                    t[12] = !written[in_ch];
                    t[13] = cfg_valid && cfg_ch == in_ch;
                    t[16:15] = in_ch;
                    tag[tail] = t; tail = (tail + 1) % 16;
                end
                if (cfg_valid) begin
                    writes = writes + 1; written[cfg_ch] = 1;
                    tm[cfg_ch] = cfg_mult; ts[cfg_ch] = cfg_shift; tz[cfg_ch] = cfg_zp;
                end
                last_accept = in_valid && in_ready;
                held = out_valid && !out_ready; held_value = {out_sat, out_data};
            end
            if (!rst_n) for (i = 0; i < CH; i = i + 1) begin tm[i] = 0; ts[i] = 0; tz[i] = 0; end
            checks = checks + 1;
            @(posedge clk); #1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT completed=%0d", completed);
        $display("COUNT writes=%0d", writes);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
