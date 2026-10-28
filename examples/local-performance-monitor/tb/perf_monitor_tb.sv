`timescale 1ns/1ps
module perf_monitor_tb;
    parameter SLOTS=4, MUTATION=0;
    reg clk=0, rst_n=1, start=0, stop=0, req_valid=0, resp_valid=0;
    reg [1:0] req_tag=0, resp_tag=0;
    wire req_ready;
    wire [15:0] total_done, window_done, window_cycles;
    wire [7:0] total_max, window_max;
    wire [2:0] active_count;
    wire error;
    perf_monitor #(.SLOTS(SLOTS), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .start(start), .stop(stop),
        .req_valid(req_valid), .req_tag(req_tag), .req_ready(req_ready),
        .resp_valid(resp_valid), .resp_tag(resp_tag),
        .total_done(total_done), .total_max(total_max),
        .window_done(window_done), .window_cycles(window_cycles), .window_max(window_max),
        .active_count(active_count), .error(error));
    always #5 clk = ~clk;
    integer fd, n, checks=0, i;
    reg [63:0] v[0:14];
    reg prev_accept=0, recovering=0;
    reg [7:0] prev_total_max=0;
    reg [15:0] oldest_time;
    reg [1:0] oldest_tag;
    reg found;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d req=%b/%0d resp=%b/%0d ready=%b done=%0d active=%0d wd=%0d wc=%0d err=%b", checks, req_valid, req_tag, resp_valid, resp_tag, req_ready, total_done, active_count, window_done, window_cycles, error); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, perf_monitor_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13], v[14]);
            if (n != 15) $fatal(1, "bad row");
            rst_n = v[0][0]; start = v[1][0]; stop = v[2][0];
            req_valid = v[3][0]; req_tag = v[4][1:0]; resp_valid = v[5][0]; resp_tag = v[6][1:0];
            #1;
            if (req_ready !== v[7][0] || total_done !== v[8][15:0] || active_count !== v[13][2:0]) fail("PERF_COUNT");
            if (window_done !== v[10][15:0] || window_cycles !== v[11][15:0] || window_max !== v[12][7:0]) fail("PERF_WINDOW");
            if (error !== v[14][0]) fail("PERF_ERROR");
            if (total_max !== v[9][7:0]) fail("PERF_LATENCY");
            if (!rst_n) begin
                recovering = 1; prev_total_max = 0;
            end else begin
                if (req_valid && req_ready) begin
                    $display("COVER request/single");
                    if (prev_accept) $display("COVER request/back-to-back");
                    if (recovering) begin $display("COVER reset/recovery"); recovering = 0; end
                end
                if (active_count >= 2) $display("COVER outstanding/two");
                if (active_count == SLOTS) $display("COVER outstanding/full");
                found = 0; oldest_time = 16'hffff; oldest_tag = 0;
                for (i = 0; i < SLOTS; i = i + 1) begin
                    if (dut.outstanding[i] && (!found || dut.start_time[i] < oldest_time)) begin
                        found = 1; oldest_time = dut.start_time[i]; oldest_tag = i;
                    end
                end
                if (resp_valid && dut.outstanding[resp_tag]) begin
                    if (found && active_count > 1 && resp_tag != oldest_tag) $display("COVER response/out-of-order");
                end else if (resp_valid) $display("COVER response/invalid");
                if (start) $display("COVER window/start");
                if (stop) $display("COVER window/stop");
                if ((start || stop) && resp_valid && dut.outstanding[resp_tag]) $display("COVER window/boundary");
                if (window_cycles > 0 && window_done > 0) $display("COVER throughput/measured");
                if (total_max > prev_total_max) $display("COVER latency/max");
                if (error) $display("COVER error/sticky");
            end
            prev_accept = req_valid && req_ready;
            prev_total_max = total_max;
            checks = checks + 1;
            @(posedge clk); #1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
