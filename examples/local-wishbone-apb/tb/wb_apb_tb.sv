`timescale 1ns/1ps
// Applies one row per clock: the Wishbone master and the APB slave are both driven from the
// row, and the bridge outputs are compared with the row and judged by protocol monitors
// that do not use the expected values.
module wb_apb_tb;
    parameter MUTATION = 0, AW = 16;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg cyc_i = 0, stb_i = 0, we_i = 0;
    reg [AW-1:0] adr_i = 0;
    reg [31:0] dat_i = 0;
    reg [3:0] sel_i = 0;
    reg pready = 0, pslverr = 0;
    reg [31:0] prdata = 0;
    wire ack_o, err_o, psel, penable, pwrite;
    wire [31:0] dat_o, pwdata;
    wire [AW-1:0] paddr;
    wire [3:0] pstrb;

    wb_apb_bridge #(.AW(AW), .MUTATION(MUTATION)) dut (.*);

    integer fd, n, checks = 0;
    reg [63:0] v [0:19];
    string vectors, wave;
    // What the previous clock looked like, for the monitors and the coverage.
    reg p_reset = 1, p_psel = 0, p_done = 0, p_answer = 0;
    reg p_pwrite = 0;
    reg [AW-1:0] p_paddr = 0;
    reg [31:0] p_pwdata = 0;
    reg [3:0] p_pstrb = 0;
    // What happened to the transfer now on APB.
    reg owner_left = 0, after_reset = 0;
    integer waited = 0;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "step=%0d", checks);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, wb_apb_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "missing input");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9],
                        v[10], v[11], v[12], v[13], v[14], v[15], v[16], v[17], v[18], v[19]);
            if (n != 20) $fatal(1, "bad row");
            rst_n = v[0][0];
            cyc_i = v[1][0];
            stb_i = v[2][0];
            we_i = v[3][0];
            adr_i = v[4][AW-1:0];
            dat_i = v[5][31:0];
            sel_i = v[6][3:0];
            pready = v[7][0];
            pslverr = v[8][0];
            prdata = v[9][31:0];
            #1;
            // 1. Comparison with the timeline of the model (switched off in the monitor-only cases).
            if (v[10][0]) begin
                if (psel !== v[14][0] || penable !== v[15][0] || pwrite !== v[16][0] || paddr !== v[17][AW-1:0] ||
                    pwdata !== v[18][31:0] || pstrb !== v[19][3:0]) fail("WBA_APB");
                if (ack_o !== v[11][0] || err_o !== v[12][0]) fail("WBA_RESPONSE");
                if (dat_o !== v[13][31:0]) fail("WBA_DATA");
            end
            // 2. Monitors: rules of the two protocols, written without the expected values.
            if ((^{ack_o, err_o, psel, penable, pwrite, pstrb, paddr, pwdata, dat_o}) === 1'bx) fail("WBA_UNKNOWN");
            if (penable && !psel) fail("WBA_APB_PROTOCOL");
            if (psel && !pwrite && pstrb != 0) fail("WBA_APB_PROTOCOL");
            if (!p_reset) begin
                // A transfer starts with exactly one setup clock.
                if (psel && !penable && p_psel && !p_done) fail("WBA_APB_PROTOCOL");
                if (penable && !p_psel) fail("WBA_APB_PROTOCOL");
                if (penable && p_done) fail("WBA_APB_PROTOCOL");
                // Once selected, the transfer stays, enabled and unchanged, until PREADY.
                if (p_psel && !p_done) begin
                    if (!psel || !penable) fail("WBA_APB_PROTOCOL");
                    if (pwrite !== p_pwrite || paddr !== p_paddr || pwdata !== p_pwdata || pstrb !== p_pstrb)
                        fail("WBA_APB_PROTOCOL");
                end
                // An answer follows a finished APB transfer, once.
                if ((ack_o || err_o) && !p_done) fail("WBA_WB_PROTOCOL");
            end
            if (ack_o && err_o) fail("WBA_WB_PROTOCOL");
            if ((ack_o || err_o) && !(cyc_i && stb_i)) fail("WBA_WB_PROTOCOL");
            if ((ack_o || err_o) && p_answer) fail("WBA_WB_PROTOCOL");
            // 3. Coverage, taken from the pins.
            if (rst_n) begin
                if (!psel && cyc_i && !stb_i) $display("COVER wb/cycle-without-strobe");
                if (!psel && cyc_i && stb_i && p_answer) $display("COVER wb/back-to-back");
                if (!psel && !cyc_i && stb_i) $display("COVER wb/strobe-without-cycle");
                if (!psel && pready) $display("COVER apb/ready-while-unselected");
                if (psel && !penable) begin
                    $display("COVER apb/setup");
                    if (pready) $display("COVER apb/ready-in-setup");
                    if (pwrite) begin
                        $display("COVER wb/write");
                        if (pstrb == 0) $display("COVER select/write-none");
                        else if (pstrb != 15) $display("COVER select/write-partial");
                    end else begin
                        $display("COVER wb/read");
                        $display("COVER apb/read-strobe-zero");
                    end
                    if (after_reset) $display("COVER reset/first-transfer");
                end
                if (psel && !cyc_i) begin
                    if (!penable) $display("COVER leave/setup");
                    else if (!pready) $display("COVER leave/wait");
                    else $display("COVER leave/complete");
                end
                if (psel && penable && !pready && pslverr) $display("COVER apb/error-flag-in-wait");
                if (psel && owner_left && cyc_i && stb_i) $display("COVER leave/new-request-waiting");
                if (psel && penable && pready) begin
                    if (waited == 0) $display("COVER apb/wait0");
                    else if (waited == 1) $display("COVER apb/wait1");
                    else $display("COVER apb/wait-many");
                    if (owner_left || !cyc_i) $display("COVER leave/no-answer");
                end
                if (p_done && !p_reset && !owner_left && !cyc_i) $display("COVER leave/response");
                if (ack_o) begin
                    $display("COVER wb/ack");
                    if (!we_i && sel_i != 15) $display("COVER select/read-mask");
                end
                if (err_o) $display("COVER wb/error");
            end else if (psel) $display("COVER reset/mid-transfer");
            // 4. Remember this clock.
            if (!rst_n) begin
                owner_left = 0; waited = 0; after_reset = 1;
            end else begin
                if (psel && !penable) begin
                    if (!p_psel || p_done) begin owner_left = 0; waited = 0; end
                    after_reset = 0;
                end
                if (psel && !cyc_i) owner_left = 1;
                if (psel && penable && !pready) waited = waited + 1;
            end
            p_reset = !rst_n;
            p_psel = psel;
            p_done = rst_n && psel && penable && pready;
            p_answer = rst_n && (ack_o || err_o);
            p_pwrite = pwrite;
            p_paddr = paddr;
            p_pwdata = pwdata;
            p_pstrb = pstrb;
            @(posedge clk);
            #1;
            checks = checks + 1;
            @(negedge clk);
        end
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
