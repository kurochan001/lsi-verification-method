`timescale 1ns/1ps
// The bench holds the cell array. A cell only goes from 0 to 1, and only after a full pulse of
// PROG cycles on its row; a pulse cut short by a loss of power changes nothing. Stuck cells are
// set by FAULT rows. Without the reference, the array also checks the rules of programming: no
// pulse while the power is off, no pulse of another length, no pulse on a locked word, and no
// pulse on the lock row before the three copies of the current write are programmed.
module otp_tb;
    parameter MUTATION = 0, NW = 16, WB = 8, PROG = 3;
    localparam AW = $clog2(NW);
    localparam RESET = 0, READ = 1, WRITE = 2, CUT = 3, FAULT = 4, KEYWRITE = 5, KEYREAD = 6, IDLE = 7;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg req_valid = 0, req_write = 0;
    reg [AW-1:0] req_addr = 0;
    reg [WB-1:0] req_wdata = 0;
    wire req_ready, resp_valid, resp_err, resp_corrected, resp_locked;
    wire [WB-1:0] resp_data, resp_any;
    wire [AW-1:0] cell_word;
    wire [1:0] cell_row;
    wire [WB-1:0] cell_rdata, prog_mask;
    wire prog_en, lc_ready;
    wire [1:0] lc_state;
    reg cs = 0, we = 0, re = 0, secure = 1, tamper = 0;
    reg [7:0] addr = 0;
    reg [31:0] wdata = 0;
    reg [15:0] debug_key = 0;
    wire [31:0] rdata;
    wire error, irq;

    otp_lifecycle_top #(.MUTATION(MUTATION), .NW(NW), .WB(WB), .PROG(PROG)) dut(
        .clk(clk), .rst_n(rst_n),
        .req_valid(req_valid), .req_write(req_write), .req_addr(req_addr), .req_wdata(req_wdata),
        .req_ready(req_ready), .resp_valid(resp_valid), .resp_data(resp_data), .resp_any(resp_any),
        .resp_err(resp_err), .resp_corrected(resp_corrected), .resp_locked(resp_locked),
        .cell_word(cell_word), .cell_row(cell_row), .cell_rdata(cell_rdata),
        .prog_en(prog_en), .prog_mask(prog_mask),
        .lc_ready(lc_ready), .lc_state(lc_state),
        .cs(cs), .we(we), .re(re), .addr(addr), .wdata(wdata), .secure(secure),
        .debug_key(debug_key), .tamper(tamper), .rdata(rdata), .error(error), .irq(irq));

    reg failed = 0;
    integer fd, n, checks = 0, lat, waited;
    task fail(input string label);
        begin
            if (!failed) begin
                failed = 1;
                $display("CHECK_FAIL %s", label);
                $fatal(1, "row=%0d time=%0t", checks, $time);
            end
        end
    endtask

    // ---- the cell array ---------------------------------------------------------------------
    reg [WB-1:0] cells [0:NW*4-1];
    reg [WB-1:0] stuck0 [0:NW*4-1];
    reg [WB-1:0] stuck1 [0:NW*4-1];
    reg [2:0] done_rows [0:NW-1];   // copies programmed since the write to the word was taken
    integer k;
    initial for (k = 0; k < NW*4; k = k + 1) begin cells[k] = 0; stuck0[k] = 0; stuck1[k] = 0; end
    initial for (k = 0; k < NW; k = k + 1) done_rows[k] = 0;

    function [WB-1:0] effective(input integer index);
        effective = (cells[index] & ~stuck0[index]) | stuck1[index];
    endfunction
    function locked_word(input integer word);
        reg [WB-1:0] bits;
        begin
            bits = effective(word*4 + 3);
            locked_word = (bits[0] & bits[1]) | (bits[1] & bits[2]) | (bits[0] & bits[2]);
        end
    endfunction

    wire [AW+1:0] index = {cell_word, cell_row};
    assign cell_rdata = (cells[index] & ~stuck0[index]) | stuck1[index];

    reg [AW+1:0] run_index = 0;
    reg [WB-1:0] run_mask = 0;
    integer run_len = 0, pulses = 0;
    always @(posedge clk) begin
        if (req_valid && req_ready && req_write) done_rows[req_addr] <= 3'b000;
        if (!rst_n && prog_en === 1'b1) fail("OTP_RESET");
        if (rst_n && prog_en === 1'bx) fail("OTP_X");
        if (rst_n && prog_en) begin
            if (run_len != 0 && index == run_index && prog_mask == run_mask) begin
                if (run_len >= PROG) fail("OTP_PULSE");              // longer than a pulse
                run_len <= run_len + 1;
                if (run_len + 1 == PROG) begin
                    cells[index] <= cells[index] | prog_mask;
                    if (cell_row != 2'd3) done_rows[cell_word][cell_row] <= 1'b1;
                    pulses <= pulses + 1;
                end
            end else begin
                if (run_len != 0 && run_len != PROG) fail("OTP_PULSE"); // the one before was short
                if (locked_word(cell_word)) fail("OTP_LOCKED");
                if (cell_row == 2'd3 && done_rows[cell_word] != 3'b111) fail("OTP_ORDER");
                if (cell_row == 2'd3 && prog_mask !== 3'b111) fail("OTP_MASK");   // only the three lock cells
                run_index <= index;
                run_mask <= prog_mask;
                run_len <= 1;
            end
        end else if (run_len != 0) begin
            // Ended: by the end of the pulse, or cut by a loss of power (then nothing is programmed).
            if (rst_n && run_len != PROG) fail("OTP_PULSE");
            run_len <= 0;
        end
    end

    // ---- the rows ---------------------------------------------------------------------------
    integer reads = 0, writes = 0, refused = 0, cuts = 0, resets = 0;
    reg [31:0] v [0:8];
    string vectors, wave;

    task power_cycle(input [1:0] expected);
        begin
            req_valid = 0; cs = 0; we = 0; re = 0;
            rst_n = 0;
            @(negedge clk);
            @(negedge clk);
            rst_n = 1;
            waited = 0;
            // While the lifecycle loads, the register block is held in reset: a key write is ignored.
            cs = 1; we = 1; re = 0; addr = 8'h00; wdata = 32'h0000dead; secure = 1;
            while (lc_ready !== 1'b1) begin
                if (req_ready !== 1'b0) fail("OTP_READY");   // the host waits for the lifecycle
                #1;
                if (error !== 1'b0) fail("LC_LOAD");
                @(negedge clk);
                waited = waited + 1;
                if (waited > 20 * PROG + 60) fail("OTP_TIMEOUT");
            end
            cs = 0; we = 0;
            if (lc_state !== expected) fail("LC_STATE");
        end
    endtask

    task request(input write, input [AW-1:0] a, input [WB-1:0] d, input hold);
        begin
            req_valid = 1; req_write = write; req_addr = a; req_wdata = d;
            #1;
            if (req_ready !== 1'b1) fail("OTP_READY");
            @(negedge clk);                     // taken at the rising edge just passed
            if (hold) begin req_write = 1; req_addr = a ^ 1'b1; req_wdata = ~d; end
            else req_valid = 0;
            lat = 0;
            while (resp_valid !== 1'b1) begin
                if (hold && req_ready !== 1'b0) fail("OTP_READY");
                @(negedge clk);
                lat = lat + 1;
                if (lat > 8 * PROG + 40) fail("OTP_TIMEOUT");
            end
            req_valid = 0;
        end
    endtask

    task check_response;
        begin
            if (^{resp_data, resp_any, resp_err, resp_corrected, resp_locked} === 1'bx) fail("OTP_X");
            if (resp_data !== v[3][WB-1:0] || resp_any !== v[4][WB-1:0]) fail("OTP_DATA");
            if (resp_err !== v[5][0]) fail("OTP_ERR");
            if (resp_corrected !== v[5][1]) fail("OTP_FLAG");
            if (resp_locked !== v[5][2]) fail("OTP_STATUS");
            if (lat != v[6]) fail("OTP_LATENCY");
            @(negedge clk);
            if (resp_valid !== 1'b0) fail("OTP_RESP");    // shown for one cycle
        end
    endtask

    task report(input [31:0] flags);
        begin
            if (flags[0]) $display("COVER read/blank");
            if (flags[1]) $display("COVER read/programmed");
            if (flags[2]) $display("COVER write/ok");
            if (flags[3]) $display("COVER write/refused-locked");
            if (flags[4]) $display("COVER write/verify-failed");
            if (flags[5]) $display("COVER fault/corrected");
            if (flags[6]) $display("COVER fault/stuck-one");
            if (flags[7]) $display("COVER cut/data");
            if (flags[8]) $display("COVER cut/lock");
            if (flags[9]) $display("COVER cut/completed-later");
            if (flags[10]) $display("COVER lc/test");
            if (flags[11]) $display("COVER lc/advanced");
            if (flags[12]) $display("COVER lc/cut-advance");
            if (flags[13]) $display("COVER lc/gap");
            if (flags[14]) $display("COVER key/allowed");
            if (flags[15]) $display("COVER key/refused");
            if (flags[16]) $display("COVER busy/held-request");
            if (flags[17]) $display("COVER idle/ready");
            if (flags[18]) $display("COVER fault/lock-row");
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, otp_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8]);
            if (n != 9) $fatal(1, "bad row");
            case (v[0])
                RESET: begin
                    power_cycle(v[3][1:0]);
                    resets = resets + 1;
                end
                READ: begin
                    request(1'b0, v[1][AW-1:0], {WB{1'b0}}, v[8][31]);
                    check_response;
                    reads = reads + 1;
                end
                WRITE: begin
                    request(1'b1, v[1][AW-1:0], v[2][WB-1:0], v[8][31]);
                    if (resp_err === 1'b1 && resp_locked === 1'b1) refused = refused + 1;
                    check_response;
                    writes = writes + 1;
                end
                CUT: begin
                    req_valid = 1; req_write = 1; req_addr = v[1][AW-1:0]; req_wdata = v[2][WB-1:0];
                    #1;
                    if (req_ready !== 1'b1) fail("OTP_READY");
                    @(negedge clk);
                    req_valid = 0;
                    repeat (v[7]) @(negedge clk);     // the power goes after that many rising edges
                    power_cycle(v[3][1:0]);
                    cuts = cuts + 1;
                end
                FAULT: begin
                    if (v[4][0]) stuck1[v[1]*4 + v[2]] = stuck1[v[1]*4 + v[2]] | (1 << v[3]);
                    else stuck0[v[1]*4 + v[2]] = stuck0[v[1]*4 + v[2]] | (1 << v[3]);
                end
                KEYWRITE: begin
                    cs = 1; we = 1; re = 0; addr = 8'h00; wdata = {16'b0, v[2][15:0]}; secure = 1;
                    #1;
                    if (error !== v[5][0]) fail("LC_ACCESS");
                    @(negedge clk);
                    cs = 0; we = 0;
                end
                KEYREAD: begin
                    cs = 1; we = 0; re = 1; addr = 8'h00; secure = 1;
                    #1;
                    if (error !== v[5][0] || rdata !== {16'b0, v[3][15:0]}) fail("LC_ACCESS");
                    @(negedge clk);
                    cs = 0; re = 0;
                end
                IDLE: begin
                    repeat (v[7]) begin
                        #1;
                        if (req_ready !== 1'b1) fail("OTP_READY");
                        @(negedge clk);
                    end
                end
                default: $fatal(1, "unknown operation");
            endcase
            report(v[8]);
            checks = checks + 1;
        end
        @(negedge clk);
        $display("COUNT steps=%0d", checks);
        $display("COUNT reads=%0d", reads);
        $display("COUNT writes=%0d", writes);
        $display("COUNT refused=%0d", refused);
        $display("COUNT cuts=%0d", cuts);
        $display("COUNT resets=%0d", resets);
        $display("COUNT pulses=%0d", pulses);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
