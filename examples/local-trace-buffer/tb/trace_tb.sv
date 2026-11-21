`timescale 1ns/1ps
// One bench for the trace buffer and the frame monitor it watches. The trace buffer samples the
// monitor's inputs {valid, data} every clock; its external trigger is the monitor's error. Each
// row is one clock: [check, rst_n, arm, post, sel, value, mask, valid, data, rd_req,
// dut_error, busy, done, kept, rd_valid, rd_data, rd_trig, rd_last] (outputs before the edge).
module trace_tb;
    parameter DEPTH = 16, MUTATION = 0;
    localparam AW = $clog2(DEPTH);
    reg clk = 0, rst_n = 0, arm = 0, trig_sel = 0, valid = 0, rd_req = 0;
    reg [AW-1:0] post = 0;
    reg [8:0] trig_value = 0, trig_mask = 0;
    reg [7:0] data = 0;
    wire dut_error, busy, done, rd_valid, rd_trig, rd_last;
    wire [AW:0] kept;
    wire [8:0] rd_data;
    frame_monitor #(.MUTATION(MUTATION == 1 ? 1 : 0)) monitor (.clk(clk), .rst_n(rst_n), .valid(valid), .data(data), .error(dut_error));
    trace_buffer #(.DEPTH(DEPTH), .W(9), .MUTATION(MUTATION >= 2 ? MUTATION : 0)) trace (
        .clk(clk), .rst_n(rst_n), .arm(arm), .post(post), .trig_sel(trig_sel), .trig_value(trig_value),
        .trig_mask(trig_mask), .ext_trig(dut_error), .sample({valid, data}), .rd_req(rd_req),
        .busy(busy), .done(done), .kept(kept), .rd_valid(rd_valid), .rd_trig(rd_trig), .rd_last(rd_last),
        .rd_data(rd_data));
    always #5 clk = ~clk;

    integer fd, n, checks = 0, captures = 0, reads = 0, errors = 0, read_since = 0, frame = 0;
    reg [15:0] v[0:17];
    reg prev_done = 0, prev_flag = 0, sel_l = 0;
    reg [AW-1:0] post_l = 0;
    reg [8:0] mask_l = 0;
    string vectors, wave;
    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d error=%b busy=%b done=%b kept=%0d rd=%b/%h/%b/%b", checks, dut_error,
                   busy, done, kept, rd_valid, rd_data, rd_trig, rd_last);
        end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, trace_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3],
                        v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13], v[14], v[15], v[16], v[17]);
            if (n != 18) $fatal(1, "bad row");
            rst_n = v[1][0]; arm = v[2][0]; post = v[3][AW-1:0]; trig_sel = v[4][0];
            trig_value = v[5][8:0]; trig_mask = v[6][8:0]; valid = v[7][0]; data = v[8][7:0]; rd_req = v[9][0];
            #1;
            if (v[0][0]) begin
                if ((^{dut_error, busy, done, kept, rd_valid, rd_trig, rd_last}) === 1'bx) fail("TR_X");
                if (dut_error !== v[10][0]) fail("TR_DUT");
                if (busy !== v[11][0] || done !== v[12][0]) fail("TR_STATUS");
                if (kept !== v[13][AW:0]) fail("TR_COUNT");
                if (rd_valid !== v[14][0] || rd_last !== v[17][0] || (rd_valid && rd_data !== v[15][8:0])) fail("TR_READ");
                if (rd_trig !== v[16][0]) fail("TR_MARK");
                // Coverage of the trace buffer.
                if (arm) begin
                    if (busy) $display("COVER arm/abort");
                    else if (done) $display("COVER arm/after-done");
                    else $display("COVER arm/from-idle");
                    sel_l = trig_sel; post_l = post; mask_l = trig_mask;
                end
                if (!rst_n && busy) $display("COVER reset/mid-capture");
                if (busy && kept == DEPTH) $display("COVER capture/full");
                if (done && !prev_done) begin
                    captures = captures + 1;
                    read_since = 0;
                    if (kept < DEPTH) $display("COVER capture/early-trigger");
                    if (post_l == 0) $display("COVER capture/post-zero");
                    if (post_l == DEPTH - 1) $display("COVER capture/post-max");
                    if (sel_l) $display("COVER trigger/external");
                    else begin
                        $display("COVER trigger/match");
                        if (mask_l != 9'h1ff) $display("COVER trigger/mask");
                    end
                end
                if (rd_req && !done) $display("COVER read/ignored-not-done");
                if (rd_req && done && read_since == kept) $display("COVER read/past-end");
                if (rd_valid) begin
                    reads = reads + 1;
                    if (rd_trig) $display("COVER read/trigger-mark");
                    if (rd_last) $display("COVER read/last");
                end
                if (rd_req && done && read_since < kept) read_since = read_since + 1;
                // Coverage of the traffic the monitor sees, counted from the specification.
                if (dut_error) begin
                    errors = errors + 1;
                    $display("COVER dut/error");
                end
                if (!rst_n) begin
                    frame = 0;
                    prev_flag = 0;
                end else if (valid) begin
                    if (data == 8'h7e) begin
                        if (prev_flag) $display("COVER dut/double-flag");
                        if (frame == 4) $display("COVER dut/max-length-frame");
                        frame = 0;
                        prev_flag = 1;
                    end else begin
                        frame = frame + 1;
                        prev_flag = 0;
                    end
                end
                prev_done = done;
            end
            @(posedge clk);
            checks = checks + 1;
            @(negedge clk);
        end
        $display("COUNT captures=%0d", captures);
        $display("COUNT reads=%0d", reads);
        $display("COUNT errors=%0d", errors);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
