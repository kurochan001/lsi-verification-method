`timescale 1ns/1ps
// Vector-driven bench: every row gives the lane inputs of one clock and the outputs expected
// before its edge. The expected values come from model.py. While pipe_en is 1 the pixel
// stream also feeds the existing Sobel pipeline, whose output is counted and summed.
module sensor_packet_tb;
    parameter LANES = 2, MAX_LINE = 8, PIPE_W = 5, PIPE_H = 4, MUTATION = 0;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, pipe_en = 0;
    reg [LANES-1:0] lane_active = 0, lane_valid = 0;
    reg [8*LANES-1:0] lane_data = 0;
    wire pix_valid, pix_first, pix_last, row_done, row_ok, frame_start, frame_end, frame_clean, hdr_fix, pkt_ignored;
    wire [7:0] pix_data;
    wire [15:0] evt_num;
    wire [5:0] err;
    sensor_packet_rx #(.LANES(LANES), .MAX_LINE(MAX_LINE), .MUTATION(MUTATION)) dut (.*);

    // The pipeline has no way to stall the link, so it must be ready whenever a pixel arrives.
    wire pipe_ready, pipe_valid, pipe_last;
    wire [7:0] pipe_pixel;
    sobel_stream #(.W(PIPE_W), .H(PIPE_H)) pipeline (
        .clk(clk), .rst_n(rst_n && pipe_en), .in_valid(pix_valid && pipe_en), .in_pixel(pix_data),
        .in_ready(pipe_ready), .out_valid(pipe_valid), .out_ready(1'b1), .out_pixel(pipe_pixel), .out_last(pipe_last));

    integer fd, n, k, checks = 0, pixels = 0, rows_ok = 0, frames_clean = 0, errors = 0, fixes = 0;
    integer pipe_pixels = 0, pipe_sum = 0;
    // One row: inputs {pipe_en, rst_n, active[3:0], valid[3:0], data[31:0]},
    // expected outputs {evt_num[15:0], pix_data[7:0], flags[15:0]}, coverage tags.
    reg [63:0] v_in, v_out, v_tags;
    wire [15:0] v_flags = v_out[15:0];
    wire [7:0] v_pix = v_out[23:16];
    wire [15:0] v_num = v_out[39:24];
    string vectors, wave;

    function automatic string goal(input integer index);
        case (index)
            0: goal = "lanes/aligned";             1: goal = "lanes/skew";
            2: goal = "lanes/skew-limit";          3: goal = "lanes/overflow";
            4: goal = "lanes/bad-sync";            5: goal = "lanes/length-mismatch";
            6: goal = "lanes/idle-strobe";         7: goal = "lanes/missing";
            8: goal = "header/clean";              9: goal = "header/corrected-data";
            10: goal = "header/corrected-check";   11: goal = "header/uncorrectable";
            12: goal = "header/reserved-bits";     13: goal = "packet/ignored-short";
            14: goal = "packet/ignored-long";      15: goal = "row/crc-ok";
            16: goal = "row/crc-error";            17: goal = "row/count-zero";
            18: goal = "row/count-max";            19: goal = "row/count-over";
            20: goal = "row/width-mismatch";       21: goal = "row/truncated";
            22: goal = "header/truncated";         23: goal = "seq/frame-clean";
            24: goal = "seq/frame-restart";        25: goal = "seq/frame-end-outside";
            26: goal = "seq/frame-number";         27: goal = "seq/frame-end-in-line";
            28: goal = "seq/line-start-outside";   29: goal = "seq/line-start-twice";
            30: goal = "seq/line-number";          31: goal = "seq/line-end-outside";
            32: goal = "seq/line-end-without-row"; 33: goal = "seq/line-end-number";
            34: goal = "seq/row-outside-line";     35: goal = "seq/row-twice";
            36: goal = "burst/multi-packet";       37: goal = "burst/partial-word";
            38: goal = "burst/too-early";          39: goal = "reset/midpacket";
            40: goal = "frame/dirty";              41: goal = "frame/dirty-other";
            default: goal = "";
        endcase
    endfunction

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d", checks);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, sensor_packet_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "input missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h\n", v_in, v_out, v_tags);
            if (n != 3) $fatal(1, "bad row");
            pipe_en = v_in[41];
            rst_n = v_in[40];
            lane_active = v_in[36 +: LANES];
            lane_valid = v_in[32 +: LANES];
            lane_data = v_in[8*LANES-1:0];
            #1;
            // Every output is compared in every row, so an unknown value is a failure too.
            if (pix_valid !== v_flags[0] || pix_first !== v_flags[1] || pix_last !== v_flags[2] ||
                pix_data !== v_pix) fail("SP_PIXEL");
            if (row_done !== v_flags[3] || row_ok !== v_flags[4]) fail("SP_ROW");
            if (frame_start !== v_flags[5] || frame_end !== v_flags[6] || frame_clean !== v_flags[7] ||
                evt_num !== v_num) fail("SP_FRAME");
            if (err !== v_flags[15:10] || hdr_fix !== v_flags[8] || pkt_ignored !== v_flags[9]) fail("SP_ERROR");
            if (pipe_en && pix_valid && pipe_ready !== 1'b1) fail("SP_PIPE");
            if (pipe_en && pipe_valid) begin
                if (^pipe_pixel === 1'bx) fail("SP_PIPE");
                pipe_sum = (pipe_sum + (pipe_pixels % 255 + 1) * pipe_pixel) & 32'h7fffffff;
                pipe_pixels = pipe_pixels + 1;
                if (pipe_last) $display("COVER pipeline/frame");
            end
            pixels = pixels + pix_valid;
            rows_ok = rows_ok + row_ok;
            frames_clean = frames_clean + frame_clean;
            errors = errors + $countones(err);
            fixes = fixes + hdr_fix;
            for (k = 0; k <= 41; k = k + 1) if (v_tags[k]) $display("COVER %s", goal(k));
            for (k = 0; k < LANES; k = k + 1) if (dut.count[k] == 3'd4 && err == 6'd0) $display("COVER lanes/queue-full");
            @(posedge clk);
            checks = checks + 1;
            @(negedge clk);
        end
        $display("COUNT pixels=%0d", pixels);
        $display("COUNT rows_ok=%0d", rows_ok);
        $display("COUNT frames_clean=%0d", frames_clean);
        $display("COUNT errors=%0d", errors);
        $display("COUNT fixes=%0d", fixes);
        $display("COUNT pipe_pixels=%0d", pipe_pixels);
        $display("COUNT pipe_sum=%0d", pipe_sum);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
