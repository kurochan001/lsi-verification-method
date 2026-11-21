`timescale 1ns/1ps
// Vector-driven bench for the encoder, the decoder and the word aligner. One row is one clock:
//   kind rst_n valid k data extra | code k_err dec_data dec_k code_err disp_err | enc_rd dec_rd |
//   word_valid word aligned realigned
// kind 0: a character into the encoder; the decoder receives the code with the bits of extra inverted.
// kind 1: one serial bit into the aligner (valid = bit_valid, k = the bit, data[0] = align_en).
// kind 2: the code in extra straight into the decoder.
// The expected values come from the Python model. Two monitors are independent of it: the longest
// run of equal bits and the running sum of the encoder's output.
module linecode_tb;
    parameter MUTATION = 0;
    reg clk = 0;
    always #5 clk = ~clk;

    reg rst_n = 0, enc_valid = 0, enc_k = 0, raw_valid = 0, align_en = 0, bit_valid = 0, bit_in = 0;
    reg [7:0] enc_data = 0;
    reg [9:0] mask = 0, raw_code = 0;
    wire [9:0] enc_code;
    wire enc_k_err, enc_rd;
    enc_8b10b #(.MUTATION(MUTATION)) enc(.clk(clk), .rst_n(rst_n), .valid(enc_valid), .k(enc_k), .data(enc_data),
        .code(enc_code), .k_err(enc_k_err), .rd(enc_rd));

    wire dec_valid = raw_valid || (enc_valid && !enc_k_err);
    wire [9:0] dec_code = raw_valid ? raw_code : enc_code ^ mask;
    wire [7:0] dec_data;
    wire dec_k, code_err, disp_err, dec_rd;
    dec_8b10b #(.MUTATION(MUTATION)) dec(.clk(clk), .rst_n(rst_n), .valid(dec_valid), .code(dec_code),
        .data(dec_data), .k(dec_k), .code_err(code_err), .disp_err(disp_err), .rd(dec_rd));

    wire word_valid, aligned, realigned;
    wire [9:0] word;
    comma_align #(.MUTATION(MUTATION)) align(.clk(clk), .rst_n(rst_n), .align_en(align_en), .bit_valid(bit_valid),
        .bit_in(bit_in), .word_valid(word_valid), .word(word), .aligned(aligned), .realigned(realigned));

    reg [15:0] kind, er, ev, ek, ed, ex, x_code, x_kerr, x_data, x_k, x_cerr, x_derr, x_erd, x_drd, x_wv, x_word, x_al, x_re;
    integer fd, rc, checks = 0, characters = 0, raw_codes = 0, words = 0, n;
    string vectors, wave;

    // Coverage state.
    reg [511:0] seen_data = 0, seen_control = 0;
    reg [2047:0] seen_raw = 0;
    integer n_data = 0, n_control = 0, n_raw = 0;
    reg [9:0] seen_flip = 0;
    reg d7_minus = 0, d7_plus = 0, a7_minus = 0, a7_plus = 0, comma_minus = 0, comma_plus = 0;
    reg after_error = 0, silent = 0, was_aligned = 0, was_plus = 0;
    reg [9:0] last_word = 0, tail = 0;
    integer tail_bits = 0;

    // Independent monitors of the encoder's output, sent a first.
    integer run = 0, sum = -1, in_word;
    reg last_bit = 0;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d kind=%0d data=%h k=%b extra=%h code=%b dec=%h.%b err=%b%b rd=%b%b word=%b.%b al=%b%b",
                   checks, kind, enc_data, enc_k, ex[9:0], enc_code, dec_data, dec_k, code_err, disp_err,
                   enc_rd, dec_rd, word, word_valid, aligned, realigned);
        end
    endtask

    function is_comma(input [6:0] seven);
        is_comma = seven == 7'b0011111 || seven == 7'b1100000;
    endfunction

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "VECTORS required");
        if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, linecode_tb); end
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        @(negedge clk);
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n", kind, er, ev, ek, ed, ex,
                         x_code, x_kerr, x_data, x_k, x_cerr, x_derr, x_erd, x_drd, x_wv, x_word, x_al, x_re);
            if (rc != 18 || kind > 2) $fatal(1, "malformed vector");
            rst_n = er[0];
            enc_valid = kind == 0 && ev[0]; enc_k = kind == 0 && ek[0]; enc_data = kind == 0 ? ed[7:0] : 8'd0;
            mask = kind == 0 ? ex[9:0] : 10'd0;
            raw_valid = kind == 2; raw_code = ex[9:0];
            bit_valid = kind == 1 && ev[0]; bit_in = kind == 1 && ek[0]; align_en = kind == 1 && ed[0];
            was_aligned = aligned; was_plus = enc_rd;
            #2;
            // Combinational outputs, valid in this cycle.
            if (enc_valid) begin
                if (enc_k_err !== x_kerr[0]) fail("LC_K_ERR");
                if (!x_kerr[0] && enc_code !== x_code[9:0]) fail("LC_CODE");
            end
            if (rst_n && enc_valid && !enc_k_err) begin
                // Longest run and running sum of what the encoder sends.
                in_word = 0;
                for (n = 9; n >= 0; n = n - 1) begin
                    run = (run != 0 && enc_code[n] == last_bit) ? run + 1 : 1;
                    last_bit = enc_code[n];
                    in_word = in_word + 1;
                    if (run > 5) fail("LC_RUN");
                    if (run == 5 && in_word >= 5) $display("COVER run/five-inside");
                    if (run == 5 && in_word < 5) $display("COVER run/five-across");
                    sum = sum + (enc_code[n] ? 1 : -1);
                end
                if (sum != 1 && sum != -1) fail("LC_DISPARITY");
            end
            if (rst_n && (raw_valid || (enc_valid && !x_kerr[0]))) begin
                if (code_err !== x_cerr[0]) fail("LC_CODE_ERR");
                if (disp_err !== x_derr[0]) fail("LC_DISP_ERR");
                if (dec_data !== x_data[7:0] || dec_k !== x_k[0]) fail("LC_DATA");
            end
            if (rst_n && enc_valid && !enc_k_err) begin
                characters = characters + 1;
                if (!enc_k && !seen_data[{enc_rd, enc_data}]) begin
                    seen_data[{enc_rd, enc_data}] = 1; n_data = n_data + 1;
                    if (n_data == 512) $display("COVER enc/all-data-both-disparities");
                end
                if (enc_k && !seen_control[{enc_rd, enc_data}]) begin
                    seen_control[{enc_rd, enc_data}] = 1; n_control = n_control + 1;
                    if (n_control == 24) $display("COVER enc/all-control-both-disparities");
                end
                if (!enc_k && enc_data[4:0] == 5'd7) begin
                    if (enc_code[9:4] == 6'b111000) d7_minus = 1;
                    if (enc_code[9:4] == 6'b000111) d7_plus = 1;
                    if (d7_minus && d7_plus) $display("COVER disparity/d7-both-forms");
                end
                if (!enc_k && enc_data[7:5] == 3'd7) begin
                    if (enc_code[3:0] == 4'b0111) a7_minus = 1;
                    if (enc_code[3:0] == 4'b1000) a7_plus = 1;
                    if (a7_minus && a7_plus) $display("COVER disparity/alternate-7");
                end
                if (mask != 0 && (mask & (mask - 10'd1)) == 0) begin
                    seen_flip = seen_flip | mask;
                    if (seen_flip == 10'h3FF) $display("COVER dec/one-bit-each-position");
                end
            end
            if (rst_n && enc_valid && enc_k_err) $display("COVER enc/illegal-control");
            if (rst_n && kind == 0 && !enc_valid && enc_rd) $display("COVER enc/idle-holds-plus");
            if (rst_n && dec_valid) begin
                if (raw_valid) begin
                    raw_codes = raw_codes + 1;
                    if (!seen_raw[{dec_rd, raw_code}]) begin
                        seen_raw[{dec_rd, raw_code}] = 1; n_raw = n_raw + 1;
                        if (n_raw == 2048) $display("COVER dec/all-codes-both-disparities");
                    end
                end
                if (code_err) $display("COVER dec/code-error");
                if (disp_err) $display("COVER dec/disparity-error");
                if (!code_err && !disp_err && after_error) $display("COVER dec/goes-on-after-error");
                // A damaged code that is accepted, and the disparity error it causes later.
                if (!raw_valid && mask != 0 && !code_err && !disp_err) silent = 1;
                if (!raw_valid && mask == 0 && disp_err && silent) $display("COVER dec/late-disparity-error");
                after_error = code_err || disp_err;
            end
            if (!rst_n) begin
                if (enc_rd || dec_rd || aligned) $display("COVER reset/mid-stream");
                run = 0; sum = -1; after_error = 0; silent = 0; tail_bits = 0; tail = 0;
            end
            if (rst_n && kind == 1 && !bit_valid && aligned) $display("COVER align/idle-cycle");
            if (rst_n && bit_valid) begin
                tail = {tail[8:0], bit_in};
                if (tail_bits < 10) tail_bits = tail_bits + 1;
                if (tail_bits == 9 && is_comma(tail[9:3]) && !x_wv[0]) $display("COVER align/needs-ten-bits");
                if (!align_en && aligned && tail_bits == 10 && is_comma(tail[9:3]) && !x_wv[0])
                    $display("COVER align/comma-ignored");
            end
            @(posedge clk); #1;
            if (enc_rd !== x_erd[0]) fail("LC_ENC_RD");
            if (dec_rd !== x_drd[0]) fail("LC_DEC_RD");
            if (word_valid !== x_wv[0] || word !== x_word[9:0]) fail("LC_WORD");
            if (aligned !== x_al[0] || realigned !== x_re[0]) fail("LC_ALIGN");
            if (word_valid) begin
                words = words + 1;
                if (!was_aligned) $display("COVER align/first-comma");
                if (is_comma(word[9:3]) && (!was_aligned || realigned)) begin
                    if (word[9]) comma_plus = 1; else comma_minus = 1;
                    if (comma_plus && comma_minus) $display("COVER align/both-polarities");
                end
                if (was_aligned && !realigned && is_comma(word[9:3])) $display("COVER align/comma-on-boundary");
                if (realigned) begin
                    $display("COVER align/realigned");
                    if (last_word == 10'b0011111000 || last_word == 10'b1100000111)
                        $display("COVER align/false-comma-after-k28-7");
                end
                last_word = word;
            end
            checks = checks + 1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT characters=%0d", characters);
        $display("COUNT raw_codes=%0d", raw_codes);
        $display("COUNT words=%0d", words);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
