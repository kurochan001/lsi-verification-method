`timescale 1us/1ns
module pwm_spice_tb;
    parameter integer MUTATION = 0;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, enable = 0, cfg_valid = 0;
    reg [3:0] cfg_duty = 0, cfg_sample = 0;
    reg signed [31:0] vin_uv = 0;
    wire pwm, adc_start, cfg_error, start_ready, busy, overrun, result_valid;
    wire [7:0] result_code;

    pwm_adc_trigger #(.MUTATION(MUTATION)) carrier(
        .clk(clk), .rst_n(rst_n), .enable(enable), .cfg_valid(cfg_valid),
        .cfg_duty(cfg_duty), .cfg_sample(cfg_sample), .cfg_error(cfg_error),
        .active_duty(), .active_sample(), .pwm(pwm), .adc_start(adc_start));
    adc_capture #(.LSB_UV(12500)) adc(
        .clk(clk), .rst_n(rst_n), .start(adc_start), .vin_uv(vin_uv), .start_ready(start_ready),
        .busy(busy), .overrun(overrun), .result_valid(result_valid), .result_ready(1'b1),
        .result_code(result_code));

    string vector_path, trace_path, wave_path;
    integer input_fd, output_fd, fields, cycles = 0, planned;
    reg [31:0] row[0:5];
    reg event_at_edge, ready_at_edge;

    initial begin
        if (!$value$plusargs("VECTORS=%s", vector_path) ||
            !$value$plusargs("CSV=%s", trace_path) ||
            !$value$plusargs("CHECKS=%d", planned))
            $fatal(1, "missing trace arguments");
        if ($value$plusargs("WAVE=%s", wave_path)) begin
            $dumpfile(wave_path);
            $dumpvars(0, pwm_spice_tb);
        end
        input_fd = $fopen(vector_path, "r");
        output_fd = $fopen(trace_path, "w");
        if (!input_fd || !output_fd) $fatal(1, "cannot open trace files");
        $fdisplay(output_fd, "cycle,pwm,trigger,cfg_error,ready,busy,overrun,valid,code");
        while (!$feof(input_fd)) begin
            fields = $fscanf(input_fd, "%h %h %h %h %h %h\n",
                row[0], row[1], row[2], row[3], row[4], row[5]);
            if (fields != 6) $fatal(1, "bad trace input");
            @(negedge clk);
            {rst_n, enable, cfg_valid, cfg_duty, cfg_sample, vin_uv} =
                {row[0][0], row[1][0], row[2][0], row[3][3:0], row[4][3:0], row[5]};
            @(posedge clk);
            {event_at_edge, ready_at_edge} = {adc_start, start_ready};
            #0.001;
            $fdisplay(output_fd,"%0d,%b,%b,%b,%b,%b,%b,%b,%0d", cycles, pwm, event_at_edge,
                cfg_error, ready_at_edge, busy, overrun, result_valid, result_code);
            cycles = cycles + 1;
        end
        if (cycles != planned) $fatal(1, "trace completion count differs");
        $fclose(input_fd);
        $fclose(output_fd);
        $display("COUNT steps=%0d", cycles);
        $display("RESULT PASS checks=%0d", cycles);
        $finish;
    end
endmodule
