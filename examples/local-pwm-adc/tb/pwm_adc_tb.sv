`timescale 1ns/1ps
module pwm_adc_tb;
    parameter integer HALF_PERIOD = 8, ACQUIRE = 2, CONVERT = 4, MUTATION = 0;
    localparam integer LEVEL_W = $clog2(HALF_PERIOD + 1);
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, enable = 0, cfg_valid = 0, result_ready = 0;
    reg [LEVEL_W-1:0] cfg_duty = 0, cfg_sample = 0;
    reg signed [31:0] vin_uv = 0;
    wire cfg_error, pwm, adc_start, start_ready, busy, overrun, result_valid;
    wire [LEVEL_W-1:0] active_duty, active_sample;
    wire [7:0] result_code;

    pwm_adc_trigger #(.HALF_PERIOD(HALF_PERIOD), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .enable(enable), .cfg_valid(cfg_valid),
        .cfg_duty(cfg_duty), .cfg_sample(cfg_sample), .cfg_error(cfg_error),
        .active_duty(active_duty), .active_sample(active_sample), .pwm(pwm), .adc_start(adc_start));
    adc_capture #(.ACQUIRE(ACQUIRE), .CONVERT(CONVERT)) adc(
        .clk(clk), .rst_n(rst_n), .start(adc_start), .vin_uv(vin_uv),
        .start_ready(start_ready), .busy(busy), .overrun(overrun), .result_valid(result_valid),
        .result_ready(result_ready), .result_code(result_code));

    string vectors, wave;
    integer fd, fields, checks = 0;
    reg [31:0] row[0:17];
    reg [11:0] hits = 0;

    task fail(input string label);
        $display("CHECK_FAIL %s", label);
        $fatal(1, "cycle=%0d period=%0d voltage_uv=%0d pwm=%b/%b duty=%0d/%0d sample=%0d/%0d trigger=%b/%b code=%h/%h (actual/expected)",
            checks, 2*HALF_PERIOD, vin_uv, pwm, row[8][0], active_duty, row[9],
            active_sample, row[10], adc_start, row[7][0], result_code, row[16][7:0]);
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "missing arguments");
        $dumpfile(wave);
        $dumpvars(0, pwm_adc_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        while (!$feof(fd)) begin
            fields = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8],
                row[9], row[10], row[11], row[12], row[13], row[14], row[15], row[16], row[17]);
            if (fields != 18) $fatal(1, "bad vector");
            @(negedge clk);
            {rst_n, enable, cfg_valid, cfg_duty, cfg_sample, vin_uv, result_ready} =
                {row[0][0], row[1][0], row[2][0], row[3][LEVEL_W-1:0],
                 row[4][LEVEL_W-1:0], row[5], row[6][0]};
            @(posedge clk);
            if (adc_start !== row[7][0]) fail("PWM_TRIGGER");
            if (start_ready !== row[12][0]) fail("PWM_ADC");
            #1;
            if ({active_duty, active_sample, cfg_error} !==
                {row[9][LEVEL_W-1:0], row[10][LEVEL_W-1:0], row[11][0]}) fail("PWM_CONFIG");
            if (pwm !== row[8][0]) fail("PWM_OUTPUT");
            if ({busy, overrun, result_valid, result_code} !==
                {row[13][0], row[14][0], row[15][0], row[16][7:0]}) fail("PWM_ADC");
            hits = hits | row[17][11:0];
            checks = checks + 1;
        end
        if (hits[0]) $display("COVER trigger/up");
        if (hits[1]) $display("COVER trigger/down-suppressed");
        if (hits[2]) $display("COVER config/apply");
        if (hits[3]) $display("COVER config/defer");
        if (hits[4]) $display("COVER config/reject");
        if (hits[5]) $display("COVER duty/zero");
        if (hits[6]) $display("COVER duty/full");
        if (hits[7]) $display("COVER enable/force-low");
        if (hits[8]) $display("COVER adc/overrun");
        if (hits[9]) $display("COVER adc/hold");
        if (hits[10]) $display("COVER adc/reset-cancel");
        if (hits[11]) $display("COVER trigger/disabled");
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
