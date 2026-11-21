`timescale 1ns/1ps
// One row of the vector file per clock, or per run of identical clocks:
//   rst_n in_valid in_re in_im | in_ready out_valid out_last overflow | exp_re exp_im | ref_re ref_im
//   tolerance | energy_low energy_high | number of clocks the row stands for
// Each bin is judged twice: against a tolerance around the mathematical transform, and bit for
// bit against the integer model. A tolerance of ffffffff marks a frame that saturates: the
// mathematical transform does not apply to it and only the bit-exact check runs.
// On the last bin of a frame the sum of |X|**2 is compared with a window that follows from the
// input samples alone (Parseval's relation).
module fft_tb;
    parameter LOGN = 4, WIDTH = 16, SCALE = 1, MUTATION = 0;
    localparam N = 1 << LOGN;
    localparam DUMP_CLOCKS = 8192;   // the waveform keeps the first clocks of a long case

    reg clk = 0;
    always #5 clk = ~clk;

    reg rst_n = 0, in_valid = 0;
    reg signed [WIDTH-1:0] in_re = 0, in_im = 0;
    wire in_ready, out_valid, out_last, overflow;
    wire signed [WIDTH-1:0] out_re, out_im;

    fft #(.LOGN(LOGN), .WIDTH(WIDTH), .SCALE(SCALE), .MUTATION(MUTATION)) dut (.*);

    integer fd, n, rows = 0, cycles = 0, k, again;
    reg [63:0] v [0:15];
    integer accepted = 0, frames = 0, outputs = 0, overflow_frames = 0, inexact = 0;
    integer exp_re, exp_im, ref_re, ref_im, got_re, got_im;
    string vectors, wave;

    // What the testbench has seen of the frame that is being loaded or sent.
    integer loaded = 0, nonzero = 0, first_re = 0, first_im = 0, bin = 0, peak_bin = 0, peaks_seen = 0;
    reg all_equal = 0, full_scale = 0, most_negative = 0, frame_inexact = 0, previous_overflow = 0;
    reg previous_out_valid = 0, any_frame = 0;
    reg [63:0] energy = 0, power = 0, peak_power = 0, second_power = 0;
    reg peak_done [0:N-1];
    localparam signed [WIDTH-1:0] TOP = {1'b0, {(WIDTH-1){1'b1}}};
    localparam signed [WIDTH-1:0] BOTTOM = {1'b1, {(WIDTH-1){1'b0}}};

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d clock=%0d", rows, cycles);
        end
    endtask

    // Report a goal once per run.
    reg reported [0:31];
    task reach(input integer id, input string goal);
        begin
            if (reported[id] !== 1'b1) begin
                reported[id] = 1'b1;
                $display("COVER %s", goal);
            end
        end
    endtask

    function integer magnitude(input integer value);
        magnitude = value < 0 ? -value : value;
    endfunction

    function [63:0] square(input integer value);
        reg [63:0] wide;
        begin
            wide = magnitude(value);
            square = wide * wide;
        end
    endfunction

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, fft_tb);
        for (k = 0; k < N; k = k + 1) peak_done[k] = 0;
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "input missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10],
                        v[11], v[12], v[13], v[14], v[15]);
            if (n != 16 || v[15] == 0) $fatal(1, "bad row");
            for (again = 0; again < v[15]; again = again + 1) begin
            rst_n = v[0][0];
            in_valid = v[1][0];
            in_re = v[2][WIDTH-1:0];
            in_im = v[3][WIDTH-1:0];
            #1;
            if (in_ready !== v[4][0]) fail("FFT_READY");
            if (out_valid !== v[5][0]) fail("FFT_VALID");
            if (out_valid) begin
                if (^{out_re, out_im, out_last, overflow} === 1'bx) fail("FFT_UNKNOWN");
                got_re = out_re;
                got_im = out_im;
                exp_re = $signed(v[8][WIDTH-1:0]);
                exp_im = $signed(v[9][WIDTH-1:0]);
                ref_re = $signed(v[10][31:0]);
                ref_im = $signed(v[11][31:0]);
                if (v[12][31:0] != 32'hffffffff &&
                    (magnitude(got_re - ref_re) > v[12][31:0] || magnitude(got_im - ref_im) > v[12][31:0]))
                    fail("FFT_TOLERANCE");
                if (out_re !== v[8][WIDTH-1:0] || out_im !== v[9][WIDTH-1:0]) fail("FFT_DATA");
                if (out_last !== v[6][0]) fail("FFT_LAST");
                if (overflow !== v[7][0]) fail("FFT_OVERFLOW");
                outputs = outputs + 1;
                if (!previous_out_valid) begin
                    bin = 0;
                    energy = 0;
                    peak_power = 0;
                    second_power = 0;
                    frame_inexact = 0;
                end
                power = square(got_re) + square(got_im);
                energy = energy + power;
                if (power > peak_power) begin
                    second_power = peak_power;
                    peak_power = power;
                    peak_bin = bin;
                end else if (power > second_power) second_power = power;
                if (v[12][31:0] != 32'hffffffff && (exp_re != ref_re || exp_im != ref_im)) begin
                    inexact = inexact + 1;
                    frame_inexact = 1;
                end
                if (overflow && (out_re === TOP || out_im === TOP)) reach(0, "saturate/positive");
                if (overflow && (out_re === BOTTOM || out_im === BOTTOM)) reach(1, "saturate/negative");
                if (out_last) begin
                    frames = frames + 1;
                    if (v[12][31:0] != 32'hffffffff) begin
                        if (energy < v[13] || energy > v[14]) fail("FFT_ENERGY");
                        if (frame_inexact) reach(2, "error/inexact");
                        else reach(3, "error/exact");
                        // One bin holds nearly all the energy: count it as the peak of this frame.
                        if (peak_power > 64 * (second_power + 1) && !peak_done[peak_bin]) begin
                            peak_done[peak_bin] = 1;
                            peaks_seen = peaks_seen + 1;
                            if (peaks_seen == N) reach(4, "peak/every-bin");
                        end
                    end
                    if (overflow) begin
                        overflow_frames = overflow_frames + 1;
                        reach(5, "overflow/set");
                    end else if (previous_overflow) reach(6, "overflow/cleared-next-frame");
                    previous_overflow = overflow;
                end
                bin = bin + 1;
            end
            if (!rst_n) begin
                if (any_frame || loaded != 0) begin
                    if (in_ready && loaded != 0) reach(7, "reset/load");
                    if (!in_ready && !out_valid) reach(8, "reset/compute");
                    if (out_valid) reach(9, "reset/send");
                end
                loaded = 0;
                previous_overflow = 0;
            end else begin
                if (in_valid && !in_ready && !out_valid) reach(11, "handshake/offer-while-computing");
                if (in_valid && !in_ready && out_valid) reach(12, "handshake/offer-while-sending");
                if (in_ready && !in_valid && loaded != 0) reach(13, "handshake/gap");
                if (in_ready && in_valid) begin
                    if (loaded == 0 && previous_out_valid) reach(14, "handshake/back-to-back");
                    accepted = accepted + 1;
                    if (loaded == 0) begin
                        nonzero = 0;
                        all_equal = 1;
                        full_scale = 0;
                        most_negative = 0;
                        first_re = in_re;
                        first_im = in_im;
                    end
                    if (in_re != 0 || in_im != 0) nonzero = nonzero + 1;
                    if (in_re != first_re || in_im != first_im) all_equal = 0;
                    if (in_re == TOP || in_im == TOP) full_scale = 1;
                    if (in_re == BOTTOM || in_im == BOTTOM) most_negative = 1;
                    loaded = loaded + 1;
                    if (loaded == N) begin
                        any_frame = 1;
                        loaded = 0;
                        if (nonzero == 0) reach(15, "input/zero");
                        if (nonzero == 1) reach(16, "input/impulse");
                        if (all_equal && nonzero == N) reach(17, "input/constant");
                        if (full_scale) reach(18, "input/full-scale");
                        if (most_negative) reach(19, "input/most-negative");
                    end
                end
            end
            previous_out_valid = rst_n && out_valid;
            @(posedge clk);
            #1;
            cycles = cycles + 1;
            if (cycles == DUMP_CLOCKS) $dumpoff;
            @(negedge clk);
            end
            rows = rows + 1;
        end
        $display("COUNT accepted=%0d", accepted);
        $display("COUNT frames=%0d", frames);
        $display("COUNT outputs=%0d", outputs);
        $display("COUNT overflow_frames=%0d", overflow_frames);
        $display("COUNT inexact=%0d", inexact);
        $display("RESULT PASS checks=%0d", rows);
        $finish;
    end
endmodule
