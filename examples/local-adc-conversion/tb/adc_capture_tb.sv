`timescale 1ns/1ps
module adc_capture_tb;
    parameter integer BITS = 8, LSB_UV = 1000, ACQUIRE = 2, CONVERT = 4, MUTATION = 0;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, start = 0, result_ready = 0;
    reg signed [31:0] vin_uv = 0;
    wire start_ready, busy, overrun, result_valid;
    wire [BITS-1:0] result_code;
    adc_capture #(.BITS(BITS), .LSB_UV(LSB_UV), .ACQUIRE(ACQUIRE),
                  .CONVERT(CONVERT), .MUTATION(MUTATION)) dut(.*);

    string vectors, wave;
    integer fd, fields, checks = 0;
    reg [31:0] row[0:9];
    reg [7:0] hits = 0;

    task fail(input string label);
        $display("CHECK_FAIL %s", label);
        $fatal(1, "cycle=%0d voltage_uv=%0d expected={ready:%b,busy:%b,overrun:%b,valid:%b,code:%h} actual={ready:%b,busy:%b,overrun:%b,valid:%b,code:%h} acquire=%0d convert=%0d",
               checks, vin_uv, row[4][0], row[5][0], row[6][0], row[7][0], row[8][BITS-1:0],
               start_ready, busy, overrun, result_valid, result_code, ACQUIRE, CONVERT);
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "missing arguments");
        $dumpfile(wave);
        $dumpvars(0, adc_capture_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        while (!$feof(fd)) begin
            fields = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h\n",
                row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9]);
            if (fields != 10) $fatal(1, "bad vector");
            @(negedge clk);
            {rst_n, start, vin_uv, result_ready} = {row[0][0], row[1][0], row[2], row[3][0]};
            @(posedge clk);
            if (start_ready !== row[4][0]) fail("ADC_READY");
            #1;
            if ({busy, overrun} !== {row[5][0], row[6][0]}) fail("ADC_BUSY");
            if (result_valid !== row[7][0]) fail("ADC_VALID");
            if (result_code !== row[8][BITS-1:0]) fail("ADC_CODE");
            hits = hits | row[9][7:0];
            checks = checks + 1;
        end
        if (hits[0]) $display("COVER adc/start");
        if (hits[1]) $display("COVER adc/capture");
        if (hits[2]) $display("COVER code/low-clamp");
        if (hits[3]) $display("COVER code/high-clamp");
        if (hits[4]) $display("COVER code/threshold");
        if (hits[5]) $display("COVER flow/overrun");
        if (hits[6]) $display("COVER flow/hold");
        if (hits[7]) $display("COVER reset/cancel");
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
