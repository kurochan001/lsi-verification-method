`timescale 1ns/1ps
// Vector-driven bench: a real-number sigma-delta modulator feeding the CIC decimator of the
// CIC example (rtl/cic_decimator.sv there, used unchanged). Each row gives the inputs of one
// clock and what the two blocks must show before its edge; the expected values come from the
// independent models in model.py. Outputs inside the measurement window (mark = 1) are logged
// for the SNR check that run.py performs after the shared runner.
//
// MUTATION 1..4: errors of the modulator model. 5..7: CIC mutations 2 (clip instead of wrap),
// 3 (comb delay lost) and 4 (decimation phase late). 8: the CIC built with one stage fewer.
module sd_tb;
    parameter ORDER = 2, STAGES = 3, MUTATION = 0;
    localparam RATE = 32;
    localparam STAGES_USED = (MUTATION == 8) ? STAGES - 1 : STAGES;
    localparam CIC_MUTATION = (MUTATION == 5) ? 2 : (MUTATION == 6) ? 3 : (MUTATION == 7) ? 4 : 0;
    localparam MOD_MUTATION = (MUTATION >= 1 && MUTATION <= 4) ? MUTATION : 0;
    localparam GAIN = RATE ** STAGES_USED;
    localparam OUT_W = 2 + $clog2(GAIN);
    localparam WINDOW = 256;
    localparam integer NEAR_FULL = 31130;          // 0.95 of full scale

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg signed [15:0] x_code = 0;
    wire y_bit;
    wire out_valid;
    wire signed [OUT_W-1:0] out_data;
    wire signed [1:0] cic_in = y_bit ? 2'sb01 : 2'sb11;

    sd_modulator_rnm #(.ORDER(ORDER), .MUTATION(MOD_MUTATION)) u_mod (
        .clk(clk), .rst_n(rst_n), .x_code(x_code), .y_bit(y_bit));
    cic_decimator #(.IN_W(2), .STAGES(STAGES_USED), .RATE(RATE), .DELAY(1), .MUTATION(CIC_MUTATION)) u_cic (
        .clk(clk), .rst_n(rst_n), .in_valid(rst_n), .sync(1'b0), .in_data(cic_in),
        .out_valid(out_valid), .out_data(out_data));

    integer fd, n, i, checks = 0, accepted = 0, outputs = 0, since_reset = 0;
    integer v[0:5];
    integer marked = 0, first_x = 0;
    bit in_window = 0, constant_x = 1, wrapped = 0, previous_rst = 0;
    longint shadow [0:3];
    longint term, limit;
    real state, peak;
    string vectors, wave;
    // Each goal is printed once per run.
    bit c_plus = 0, c_minus = 0, c_zero = 0, c_max = 0, c_min = 0, c_out = 0, c_pos = 0, c_neg = 0;
    bit c_after = 0, c_over = 0;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "cycle=%0d", checks);
        end
    endtask

    task end_window;
        begin
            if (marked == WINDOW) $display("COVER snr/window");
            if (marked == WINDOW && constant_x && first_x != 0) $display("COVER idle/dc");
            $display("OBS SD peak_milli=%0d", $rtoi(peak * 1000.0));
            in_window = 0;
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, sd_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "input missing");
        limit = 64'sd1 <<< (OUT_W - 1);
        for (i = 0; i < 4; i = i + 1) shadow[i] = 0;
        peak = 0.0;
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5]);
            if (n != 6) $fatal(1, "bad row");
            if (!v[0] && previous_rst && since_reset > RATE) $display("COVER reset/midstream");
            rst_n = v[0];
            x_code = v[1];
            #1;
            // The decision first, then the decimated output: time, then value.
            if (y_bit !== v[2][0]) fail("SD_BITS");
            if (out_valid !== v[3][0]) fail("SD_VALID");
            if (out_valid && out_data !== v[4][OUT_W-1:0]) fail("SD_CIC");
            state = (ORDER == 1) ? u_mod.s1 : u_mod.s2;
            if (rst_n) begin
                if (y_bit && !c_plus) begin c_plus = 1; $display("COVER mod/plus"); end
                if (!y_bit && !c_minus) begin c_minus = 1; $display("COVER mod/minus"); end
                if (state == 0.0 && !c_zero) begin c_zero = 1; $display("COVER mod/zero-decision"); end
                if (x_code == 16'sh7fff && !c_max) begin c_max = 1; $display("COVER input/max"); end
                if (x_code == 16'sh8000 && !c_min) begin c_min = 1; $display("COVER input/min"); end
            end
            if (out_valid) begin
                outputs = outputs + 1;
                if (!c_out) begin c_out = 1; $display("COVER cic/output"); end
                if (out_data > 0 && !c_pos) begin c_pos = 1; $display("COVER cic/positive"); end
                if (out_data < 0 && !c_neg) begin c_neg = 1; $display("COVER cic/negative"); end
                if (wrapped && !c_after) begin c_after = 1; $display("COVER cic/output-after-wrap"); end
            end
            if (v[5][0]) begin
                if (!in_window) begin
                    in_window = 1;
                    marked = 0;
                    constant_x = 1;
                    first_x = x_code;
                    peak = 0.0;
                end
                if (x_code != first_x) constant_x = 0;
                if ((x_code >= NEAR_FULL || x_code <= -NEAR_FULL) && !c_over) begin
                    c_over = 1;
                    $display("COVER overload/window");
                end
                if (state > peak) peak = state;
                if (-state > peak) peak = -state;
                if (out_valid) begin
                    marked = marked + 1;
                    $display("OBS SD y=%0d", out_data);
                end
            end else if (in_window) begin
                end_window();
            end
            // What the integrators would hold without wrapping, in 64 bits.
            if (!rst_n) begin
                for (i = 0; i < 4; i = i + 1) shadow[i] = 0;
                wrapped = 0;
                since_reset = 0;
            end else begin
                accepted = accepted + 1;
                since_reset = since_reset + 1;
                term = y_bit ? 1 : -1;
                for (i = 0; i < STAGES_USED; i = i + 1) begin
                    shadow[i] = shadow[i] + term;
                    term = shadow[i];
                    if (shadow[i] >= limit || shadow[i] < -limit) begin
                        if (!wrapped) $display("COVER cic/wrap");
                        wrapped = 1;
                    end
                end
            end
            previous_rst = rst_n;
            @(posedge clk);
            checks = checks + 1;
            @(negedge clk);
        end
        if (in_window) end_window();
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT outputs=%0d", outputs);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
