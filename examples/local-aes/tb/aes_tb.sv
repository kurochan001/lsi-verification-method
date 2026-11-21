`timescale 1ns/1ps
// Row-driven bench. Each row gives the inputs of one clock and the expected outputs before its edge;
// the expected values come from run.py (control schedule) and model.py (ciphertexts).
module aes_tb;
    parameter MUTATION = 0;
    reg clk = 1'b0;
    always #5 clk = ~clk;
    reg rst_n = 1'b0, start = 1'b0, cancel = 1'b0, out_ready = 1'b0;
    reg [127:0] key = 128'h0, block = 128'h0;
    wire ready, busy, out_valid;
    wire [3:0] progress;
    wire [127:0] out_block;
    aes128_core #(.MUTATION(MUTATION)) dut(.*);

    localparam [127:0] FIPS_B = 128'h3925841d02dc09fbdc118597196a0b32;
    localparam [127:0] FIPS_C1 = 128'h69c4e0d86a7b0430d8cdb78070b4c55a;
    localparam [127:0] ONES = {128{1'b1}};
    integer fd, n, steps = 0, results = 0, latency = 0;
    reg [127:0] v[0:10];
    reg prev_valid = 1'b0, prev_handshake = 1'b0, prev_cancel = 1'b0, prev_reset = 1'b0, counting = 1'b0;
    reg [127:0] prev_key = 128'h0, prev_block = 128'h0;
    reg inflight, accept;
    string vectors, wave;

    task automatic fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "step=%0d", steps);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, aes_tb);
        fd = $fopen(vectors, "r");
        if (fd == 0) $fatal(1, "missing input");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
            if (n != 11) $fatal(1, "bad row");
            rst_n = v[0][0]; start = v[1][0]; cancel = v[2][0]; out_ready = v[3][0];
            key = v[4]; block = v[5];
            #1;
            // A difference while an accepted operation is in flight, or at the first result
            // clock, is a timing difference; elsewhere it is a handshake difference.
            inflight = v[7][0] || (v[8][0] && !prev_valid);
            if (ready !== v[6][0] || busy !== v[7][0] || out_valid !== v[8][0] || progress !== v[9][3:0])
                fail(inflight ? "AES_TIMING" : "AES_FLOW");
            if (!v[7][0] && !v[8][0] && (dut.state !== 128'h0 || dut.rkey !== 128'h0 || dut.rcon !== 8'h00))
                fail("AES_ZERO");
            if (v[8][0] && (dut.rkey !== 128'h0 || dut.rcon !== 8'h00)) fail("AES_ZERO");
            if (!v[8][0] && out_block !== 128'h0) fail("AES_LEAK");
            if (v[8][0] && out_block !== v[10]) fail("AES_DATA");
            if (out_valid && !prev_valid) begin
                if (!counting || latency != 11) fail("AES_TIMING");
                $display("COVER timing/fixed-latency");
                counting = 1'b0;
            end
            if (!v[7][0] && !v[8][0]) begin
                if (prev_cancel) $display("COVER clear/after-cancel");
                if (prev_reset) $display("COVER clear/after-reset");
                if (prev_handshake) $display("COVER clear/after-result");
            end
            if (out_valid && out_block == FIPS_B) $display("COVER vector/fips-b");
            if (out_valid && out_block == FIPS_C1) $display("COVER vector/fips-c1");
            accept = rst_n && !cancel && start && ready;
            if (!rst_n) begin
                if (busy) $display("COVER reset/busy");
                if (out_valid) $display("COVER reset/holding");
            end else if (cancel) begin
                if (busy) $display("COVER cancel/busy");
                if (out_valid) $display("COVER cancel/holding");
                if (ready && !start) $display("COVER cancel/idle");
                if (ready && start) $display("COVER cancel/with-start");
            end else begin
                if (ready && !start) $display("COVER flow/idle-gap");
                if (start && busy) $display("COVER flow/start-while-busy");
                if (start && out_valid) $display("COVER flow/start-while-holding");
                if (out_valid && !out_ready) $display("COVER flow/hold");
                if (busy && (key != prev_key || block != prev_block)) $display("COVER flow/inputs-change-busy");
                if (accept && prev_handshake) $display("COVER flow/back-to-back");
                if (accept && block == 128'h0) $display("COVER data/zero-block");
                if (accept && key == 128'h0) $display("COVER data/zero-key");
                if (accept && block == ONES) $display("COVER data/ones-block");
                if (accept && key == ONES) $display("COVER data/ones-key");
                if (out_valid && out_ready) results = results + 1;
            end
            prev_valid = v[8][0];
            prev_handshake = rst_n && !cancel && out_valid && out_ready;
            prev_cancel = rst_n && cancel;
            prev_reset = !rst_n;
            prev_key = key;
            prev_block = block;
            if (!rst_n || cancel) counting = 1'b0;
            @(posedge clk);
            #1;
            steps = steps + 1;
            if (counting) latency = latency + 1;
            if (accept) begin
                counting = 1'b1;
                latency = 1;
            end
            @(negedge clk);
        end
        $display("COUNT steps=%0d", steps);
        $display("COUNT results=%0d", results);
        $display("RESULT PASS checks=%0d", steps);
        $finish;
    end
endmodule
