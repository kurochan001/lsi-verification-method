`timescale 1ns/1ps
module systolic_tb;
    parameter N=4, MUTATION=0;
    localparam SLOTS = 2*N-1;
    reg clk=0, rst_n=0, w_valid=0, a_valid=0, c_ready=0;
    reg [$clog2(N)-1:0] w_row=0;
    reg [8*N-1:0] w_data=0, a_data=0;
    wire w_ready, a_ready, c_valid;
    wire [32*N-1:0] c_data;
    systolic_array #(.N(N), .MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer fd, n, checks=0, accepted=0, completed=0, writes=0, results=0, inflight=0, head=0, tail=0, r, c, sum;
    reg [127:0] v[0:10];
    reg [32*N-1:0] held_data;
    reg held=0, cleared=1, last_accept=0, gap=0;
    reg [N-1:0] rows_written=0;
    reg signed [7:0] tw[0:N*N-1];  // weights the TB saw accepted
    reg [3:0] tag[0:15];           // events of each accepted vector, credited at its result
    reg [3:0] t;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "cycle=%0d c_valid=%b c_data=%h", checks, c_valid, c_data); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave); $dumpvars(0, systolic_tb);
        for (r = 0; r < N*N; r = r + 1) tw[r] = 0;
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
            if (n != 11) $fatal(1, "bad row");
            if (!v[0][0] && rst_n && inflight != 0) $display("COVER reset/in-flight");
            rst_n = v[0][0]; w_valid = v[1][0]; w_row = v[2]; w_data = v[3];
            a_valid = v[4][0]; a_data = v[5]; c_ready = v[6][0];
            #1;
            if (w_ready !== v[7][0] || a_ready !== v[8][0] || c_valid !== v[9][0]) fail("SA_CONTROL");
            if (rst_n && held && c_data !== held_data) fail("SA_HOLD");
            if (c_valid && c_data !== v[10][32*N-1:0]) fail("SA_DATA");
            if (!rst_n) begin
                held = 0; inflight = 0; head = 0; tail = 0; results = 0; cleared = 1;
                rows_written = 0; last_accept = 0; gap = 0;
                for (r = 0; r < N*N; r = r + 1) tw[r] = 0;
            end else begin
                if (inflight == SLOTS) $display("COVER flow/pipeline-full");
                if (c_valid && !c_ready) begin
                    $display("COVER stall/output-held");
                    if (inflight == SLOTS) $display("COVER stall/full");
                end
                if (a_valid && !a_ready && !w_valid) $display("COVER stall/input-blocked");
                if (w_valid && !w_ready) $display("COVER weight/blocked-in-flight");
                if (w_valid && w_ready && a_valid) $display("COVER weight/priority");
                if (c_valid && c_ready) begin
                    completed = completed + 1; results = results + 1; inflight = inflight - 1;
                    t = tag[head]; head = (head + 1) % 16;
                    if (t[0]) $display("COVER product/max-positive");
                    if (t[1]) $display("COVER product/max-negative");
                    if (t[2]) $display("COVER sum/beyond-16bit");
                    if (t[3]) $display("COVER reset/weights-cleared");
                    for (c = 0; c < N; c = c + 1)
                        if ($signed(c_data[32*c +: 32]) < 0) $display("COVER result/negative");
                        else if (c_data[32*c +: 32] == 0) $display("COVER result/zero");
                        else $display("COVER result/positive");
                end
                if (a_valid && a_ready) begin
                    accepted = accepted + 1;
                    if (last_accept) $display("COVER flow/back-to-back");
                    else if (gap && inflight != 0) $display("COVER flow/bubble");
                    t = {cleared, 3'b000};
                    for (c = 0; c < N; c = c + 1) begin
                        sum = 0;
                        for (r = 0; r < N; r = r + 1) begin
                            sum = sum + $signed(a_data[8*r +: 8]) * tw[r*N + c];
                            if ($signed(a_data[8*r +: 8]) == -128 && tw[r*N + c] == -128) t[0] = 1;
                            if ($signed(a_data[8*r +: 8]) * tw[r*N + c] == -16256) t[1] = 1;
                        end
                        if (sum > 32767 || sum < -32768) t[2] = 1;
                    end
                    tag[tail] = t; tail = (tail + 1) % 16; inflight = inflight + 1;
                end
                if (w_valid && w_ready) begin
                    writes = writes + 1; cleared = 0;
                    if (results != 0) $display("COVER weight/reload");
                    for (c = 0; c < N; c = c + 1) tw[w_row*N + c] = w_data[8*c +: 8];
                    rows_written[w_row] = 1;
                    if (&rows_written) $display("COVER weight/all-rows");
                end
                gap = !(c_valid && !c_ready) && !(a_valid && a_ready);
                last_accept = a_valid && a_ready;
                held = c_valid && !c_ready; held_data = c_data;
            end
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
