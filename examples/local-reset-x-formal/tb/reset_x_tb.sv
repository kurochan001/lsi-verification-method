`timescale 1ns/1ps
// Applies one row per clock cycle and compares what the design shows after the edge with the
// reference. Nothing in the design is given a value before the first edge unless the first row
// asks for it, so the run starts from X as an RTL simulation does.
// Outputs are compared with !==, so an X where a value is specified is an error.
module reset_x_tb;
    parameter MUTATION = 0, WIDTH = 8, STAGES = 3;
    localparam CW = $clog2(STAGES);

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst = 0, in_valid = 0, cfg_we = 0, cfg_step2 = 0;
    reg [WIDTH-1:0] in_data = 0;
    wire ready, out_valid, odd, err, step_o;
    wire [WIDTH-1:0] out_data;
    wire [3:0] count;
    wire [STAGES-1:0] stage_valid_o;
    wire [STAGES*WIDTH-1:0] stage_data_o;
    wire [CW-1:0] init_o;

    reset_x_unit #(.MUTATION(MUTATION), .WIDTH(WIDTH), .STAGES(STAGES)) dut(
        .clk(clk), .rst(rst), .in_valid(in_valid), .in_data(in_data), .cfg_we(cfg_we), .cfg_step2(cfg_step2),
        .ready(ready), .out_valid(out_valid), .out_data(out_data), .odd(odd), .count(count), .err(err),
        .stage_valid_o(stage_valid_o), .stage_data_o(stage_data_o), .init_o(init_o), .step_o(step_o));

    integer fd, n, checks = 0, k;
    integer outputs = 0, resets = 0, refused = 0, reset_run = 0;
    reg [31:0] v [0:14];
    reg failed = 0, started = 0, was_valid = 0, was_err = 0, was_ready = 0, had_reset = 0;
    reg [3:0] was_count = 0;
    string vectors, wave;

    task fail(input string label);
        begin
            if (!failed) begin
                failed = 1;
                $display("CHECK_FAIL %s", label);
                $fatal(1, "row=%0d time=%0t", checks, $time);
            end
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "missing +VECTORS");
        if ($value$plusargs("WAVE=%s", wave)) begin
            $dumpfile(wave);
            $dumpvars(0, reset_x_tb);
        end
        fd = $fopen(vectors, "r");
        if (fd == 0) $fatal(1, "cannot open vectors");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4],
                        v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13], v[14]);
            if (n != 15) $fatal(1, "bad vector row");
            if (v[0] == 1) begin
                // Power-up with chosen register values instead of X. Only as the first row.
                if (checks != 0) $fatal(1, "power row after the start");
                dut.init = v[1][CW-1:0];
                dut.step = v[2][0];
                dut.v = v[3][STAGES-1:0];
                dut.d = {STAGES{v[4][WIDTH-1:0]}};
                dut.count = v[5][3:0];
                dut.err = v[6][0];
                if (v[7] == 0) $display("COVER power/zeros");
                else if (v[7] == 1) $display("COVER power/ones");
                else $display("COVER power/mixed");
            end else begin
                if (checks == 0 || (checks == 1 && !had_reset && $isunknown(count))) begin
                    if ($isunknown(dut.v) && $isunknown(dut.d) && $isunknown(dut.init)) $display("COVER power/x");
                end
                // The first cycle starts at time 0, so that no clock edge comes before the first row.
                if (started) @(negedge clk);
                started = 1;
                rst = v[1][0]; in_valid = v[2][0]; in_data = v[3][WIDTH-1:0]; cfg_we = v[4][0]; cfg_step2 = v[5][0];
                if (rst) begin
                    resets = resets + 1;
                    reset_run = reset_run + 1;
                    if (had_reset && |stage_valid_o === 1'b1) $display("COVER reset/in-flight");
                    if (had_reset && err === 1'b1) $display("COVER err/cleared");
                    if (reset_run == 3) $display("COVER reset/long");
                end else begin
                    if (reset_run == 1) $display("COVER reset/one-cycle");
                    reset_run = 0;
                    if (in_valid && ready === 1'b0) begin
                        refused = refused + 1;
                        $display("COVER flush/refused");
                    end
                end
                was_valid = out_valid === 1'b1; was_err = err === 1'b1; was_ready = ready === 1'b1;
                was_count = count;
                @(posedge clk);
                #1;
                had_reset = 1;
                if (ready !== v[6][0]) fail("RX_READY");
                if (out_valid !== v[7][0]) fail("RX_VALID");
                if (v[7][0] && out_data !== v[8][WIDTH-1:0]) fail("RX_DATA");
                if (odd !== v[9][0]) fail("RX_ODD");
                if (count !== v[10][3:0]) fail("RX_COUNT");
                if (err !== v[11][0]) fail("RX_ERR");
                // Registers: each valid bit the reference knows, and the flush counter.
                for (k = 0; k < STAGES; k = k + 1)
                    if (v[12][k] && stage_valid_o[k] !== v[13][k]) fail("RX_REG");
                if (init_o !== v[14][CW-1:0]) fail("RX_REG");
                if (ready && !was_ready) begin
                    $display("COVER flush/ready");
                    if (!$isunknown(stage_valid_o)) $display("COVER flush/stages-known");
                end
                if (ready && !out_valid && $isunknown(out_data)) $display("COVER data/unknown-hidden");
                if (out_valid) begin
                    outputs = outputs + 1;
                    $display("COVER data/passed");
                    if (odd) $display("COVER data/odd");
                    else $display("COVER data/even");
                    if (was_valid) $display("COVER data/back-to-back");
                end
                if (was_valid && !rst) begin
                    if (count == was_count + 4'd1) $display("COVER count/step1");
                    if (count == was_count + 4'd2) $display("COVER count/step2");
                    if (count < was_count) $display("COVER count/wrap");
                end
                if (err && !was_err) $display("COVER err/set");
                if (err && was_err && !in_valid) $display("COVER err/sticky");
            end
            checks = checks + 1;
        end
        $fclose(fd);
        $display("COUNT outputs=%0d", outputs);
        $display("COUNT resets=%0d", resets);
        $display("COUNT refused=%0d", refused);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
