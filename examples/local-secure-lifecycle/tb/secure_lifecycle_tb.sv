`timescale 1ns/1ps
module secure_lifecycle_tb;
    parameter MUTATION=0, ATTEMPT_LIMIT=3, DEBUG_KEY=16'ha55a;
    reg clk=0, rst_n=1, cs=0, we=0, re=0, secure=0, tamper=0;
    reg [7:0] addr=0;
    reg [31:0] wdata=0;
    reg [1:0] lifecycle=0;
    reg [15:0] debug_key=0;
    wire [31:0] rdata;
    wire error, irq;
    secure_lifecycle #(.MUTATION(MUTATION), .ATTEMPT_LIMIT(ATTEMPT_LIMIT), .DEBUG_KEY(DEBUG_KEY)) dut(
        .clk(clk), .rst_n(rst_n), .cs(cs), .we(we), .re(re), .addr(addr), .wdata(wdata),
        .secure(secure), .lifecycle(lifecycle), .debug_key(debug_key), .tamper(tamper),
        .rdata(rdata), .error(error), .irq(irq));
    always #5 clk = ~clk;
    integer fd, n, checks=0;
    reg [63:0] v[0:12];
    reg recovering=0, prev_unlocked=0, prev_lockout=0;
    reg [15:0] prev_key0=0, prev_key1=0;
    reg [7:0] index;
    reg known_addr;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d addr=%h error=%b rdata=%h", checks, addr, error, rdata); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, secure_lifecycle_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12]);
            if (n != 13) $fatal(1, "bad row");
            rst_n = v[0][0]; cs = v[1][0]; we = v[2][0]; re = v[3][0]; addr = v[4][7:0];
            wdata = v[5][31:0]; secure = v[6][0]; lifecycle = v[7][1:0];
            debug_key = v[8][15:0]; tamper = v[9][0]; index = addr;
            known_addr = (addr[1:0] == 0) && (index == 8'h00 || index == 8'h04 || index == 8'h08 ||
                index == 8'h0c || index == 8'h10 || index == 8'h14 || index == 8'h18 || index == 8'h1c);
            #1;
            if (rdata !== v[10][31:0]) fail("SECURE_DATA");
            if (error !== v[11][0]) fail("SECURE_ACCESS");
            if (irq !== v[12][0]) fail("SECURE_IRQ");
            if (!rst_n) begin
                recovering = 1; prev_unlocked = 0; prev_lockout = 0;
            end else begin
                if (cs) begin
                    if (re && !error) begin
                        if (secure && (index == 8'h00 || index == 8'h04 || index == 8'h08 || index == 8'h0c ||
                            index == 8'h10 || index == 8'h14)) $display("COVER access/secure-read");
                        if (index == 8'h18 || index == 8'h1c) $display("COVER access/write-only-read");
                        if (index == 8'h0c) $display("COVER status/observable");
                        if (index == 8'h0c && rdata[2]) $display("COVER tamper/observable");
                    end
                    if (re && error && !secure) $display("COVER access/nonsecure-denied");
                    if ((re || we) && !known_addr) $display("COVER access/unknown");
                    if (we && error) $display("COVER reject/denied-write");
                    if (we && index == 8'h18 && wdata[0] && !error) $display("COVER lock/set");
                    if (we && error && dut.locked && (index == 8'h00 || index == 8'h08)) $display("COVER lock/sticky");
                    if (we && index == 8'h14 && !error && wdata[1:0] != 0) $display("COVER irq/w1c");
                    if (recovering && !error) begin $display("COVER reset/recovery"); recovering = 0; end
                end
                if (dut.debug_unlocked && !prev_unlocked) $display("COVER debug/success");
                if (dut.debug_lockout && !prev_lockout) $display("COVER debug/lockout");
                if (cs && we && index == 8'h1c && !dut.debug_unlocked && debug_key != DEBUG_KEY && !error)
                    $display("COVER debug/wrong");

            end
            prev_unlocked = dut.debug_unlocked; prev_lockout = dut.debug_lockout;
            prev_key0 = dut.key0; prev_key1 = dut.key1;
            checks = checks + 1;
            @(posedge clk); #1;
            if (rst_n && tamper) begin
                if (dut.key0 !== 0 || dut.key1 !== 0 || !dut.tamper_latched || !irq) fail("SECURE_DATA");
                if (prev_key0 != 0 || prev_key1 != 0) $display("COVER tamper/zeroize");
            end
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
