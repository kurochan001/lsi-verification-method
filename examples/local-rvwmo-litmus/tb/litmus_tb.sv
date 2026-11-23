`timescale 1ns/1ps
module litmus_tb;
    parameter DRAIN=2, MUTATION=0;
    reg clk=0, rst_n=1, issue0=0, issue1=0, read0=0, read1=0, fence0=0, fence1=0;
    wire x, y, vis0, vis1, busy0, busy1, fwait0, fwait1, done0, done1, r0, r1;
    litmus #(.DRAIN(DRAIN), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .issue0(issue0), .issue1(issue1),
        .read0(read0), .read1(read1), .fence0(fence0), .fence1(fence1),
        .x(x), .y(y), .vis0(vis0), .vis1(vis1),
        .busy0(busy0), .busy1(busy1), .fwait0(fwait0), .fwait1(fwait1),
        .done0(done0), .done1(done1), .r0(r0), .r1(r1));
    always #5 clk = ~clk;
    integer fd, n, checks=0;
    reg [63:0] v[0:19];
    reg vis0_prev=0, vis1_prev=0, done0_prev=0, done1_prev=0, recovering=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d i=%b%b%b%b%b%b r=%b%b done=%b%b vis=%b%b x=%b y=%b", checks, issue0, issue1, read0, read1, fence0, fence1, r0, r1, done0, done1, vis0, vis1, x, y); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, litmus_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9],
                        v[10], v[11], v[12], v[13], v[14], v[15], v[16], v[17], v[18], v[19]);
            if (n != 20) $fatal(1, "bad row");
            rst_n = v[0][0]; issue0 = v[1][0]; issue1 = v[2][0]; read0 = v[3][0]; read1 = v[4][0];
            fence0 = v[5][0]; fence1 = v[6][0];
            #1;
            // The property comes first, and only in fenced rounds: a fence bypass
            // must read as an ordering failure, not a silent data mismatch.
            if (v[19][0] && done0 && done1 && !r0 && !r1) fail("MEM_ORD");
            if (x !== v[7][0] || y !== v[8][0]) fail("MEM_DATA");
            if (vis0 !== v[9][0] || vis1 !== v[10][0]) fail("MEM_DATA");
            if (busy0 !== v[11][0] || busy1 !== v[12][0]) fail("MEM_DATA");
            if (fwait0 !== v[13][0] || fwait1 !== v[14][0]) fail("MEM_DATA");
            if (done0 !== v[15][0] || done1 !== v[16][0]) fail("MEM_DATA");
            if (r0 !== v[17][0] || r1 !== v[18][0]) fail("MEM_DATA");
            if ((vis0 && !vis0_prev) || (vis1 && !vis1_prev)) begin
                $display("COVER mm/st-drain");
                if (recovering) $display("COVER mm/reset-recovery");
            end
            if ((read0 && busy0 && !done0) || (read1 && busy1 && !done1)) $display("COVER mm/read-ahead");
            if (done0 && !done0_prev) begin
                if (!r0) $display("COVER mm/read-zero"); else $display("COVER mm/read-one");
            end
            if (done1 && !done1_prev) begin
                if (!r1) $display("COVER mm/read-zero"); else $display("COVER mm/read-one");
            end
            if (done0 && done1 && r0 && r1) $display("COVER mm/both-one");
            if (done0 && done1 && (r0 ^ r1)) $display("COVER mm/mixed-outcome");
            vis0_prev = vis0; vis1_prev = vis1; done0_prev = done0; done1_prev = done1;
            if (!rst_n) recovering = 1;
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
