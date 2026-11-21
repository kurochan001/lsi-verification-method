`timescale 1ns/1ps
// Vector-driven bench: every row gives the inputs of one clock and the outputs expected before
// its edge. The expected values come from the moving-sum model in run.py.
module cic_tb;
    parameter IN_W = 8, STAGES = 3, RATE = 4, DELAY = 1, MUTATION = 0;
    localparam GAIN = (RATE * DELAY) ** STAGES;
    localparam OUT_W = IN_W + $clog2(GAIN);
    localparam signed [OUT_W-1:0] OUT_MIN = -(1 <<< (IN_W - 1)) * GAIN;
    localparam signed [OUT_W-1:0] OUT_MAX = ((1 <<< (IN_W - 1)) - 1) * GAIN;
    localparam signed [OUT_W-1:0] HALF = 1 <<< (OUT_W - 2);

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, in_valid = 0, sync = 0;
    reg signed [IN_W-1:0] in_data = 0;
    wire out_valid;
    wire signed [OUT_W-1:0] out_data;
    cic_decimator #(.IN_W(IN_W), .STAGES(STAGES), .RATE(RATE), .DELAY(DELAY), .MUTATION(MUTATION)) dut (.*);

    integer fd, n, v[0:5], checks = 0, accepted = 0, outputs = 0;
    integer since_restart = 0, phase_at_sync = 0;
    bit gap_in_period = 0, wrapped = 0, realigned = 0, first_pending = 0;
    reg signed [OUT_W-1:0] first_before;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "cycle=%0d", checks);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, cic_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "input missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5]);
            if (n != 6) $fatal(1, "bad row");
            if (!v[0] && rst_n && since_restart % RATE != 0 && since_restart > RATE) $display("COVER reset/midstream");
            rst_n = v[0];
            in_valid = v[1];
            sync = v[2];
            in_data = v[3];
            #1;
            // Outputs first: a wrong time is reported as CIC_VALID, a wrong value as CIC_DATA.
            if (out_valid !== v[4][0]) fail("CIC_VALID");
            if (out_valid && out_data !== v[5][OUT_W-1:0]) fail("CIC_DATA");
            if (out_valid) begin
                outputs = outputs + 1;
                if (out_data == 0) $display("COVER result/zero");
                else if (out_data < 0) $display("COVER result/negative");
                else $display("COVER result/positive");
                if (out_data == OUT_MIN) $display("COVER range/min");
                if (out_data == OUT_MAX) $display("COVER range/max");
                if (out_data >= HALF) $display("COVER msb/positive");
                if (out_data < -HALF) $display("COVER msb/negative");
                if (wrapped) $display("COVER wrap/output-after-wrap");
                if (first_pending) begin
                    $display("COVER phase/first-output");
                    if (realigned) $display("COVER phase/sync-realign");
                    first_pending = 0;
                    realigned = 0;
                end
            end
            if (!rst_n) begin
                since_restart = 0;
                gap_in_period = 0;
                wrapped = 0;
                first_pending = 0;
                realigned = 0;
            end else if (sync) begin
                if (in_valid) $display("COVER sync/discard-sample");
                phase_at_sync = since_restart % RATE;
                realigned = phase_at_sync != 0;
                since_restart = 0;
                gap_in_period = 0;
                wrapped = 0;
                first_pending = 0;
            end else if (in_valid) begin
                accepted = accepted + 1;
                since_restart = since_restart + 1;
                first_before = dut.integ[0];
                if (since_restart % RATE == 0) begin
                    if (gap_in_period) $display("COVER phase/gap");
                    gap_in_period = 0;
                    if (since_restart == RATE) first_pending = 1;
                end
            end else if (since_restart % RATE != 0) begin
                gap_in_period = 1;
            end
            @(posedge clk);
            #1;
            // The first integrator went around: same-sign operands, opposite-sign sum.
            if (rst_n && !sync && in_valid && first_before[OUT_W-1] == in_data[IN_W-1] &&
                dut.integ[0][OUT_W-1] != in_data[IN_W-1] && (in_data != 0)) begin
                wrapped = 1;
                $display("COVER wrap/integrator");
            end
            checks = checks + 1;
            @(negedge clk);
        end
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT outputs=%0d", outputs);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
