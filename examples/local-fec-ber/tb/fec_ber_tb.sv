`timescale 1ns/1ps
// Vector-driven bench: encoder -> channel (XOR with an error pattern) -> decoder.
// A row is one clock cycle, or (op 3) one whole frame that the bench expands into the same
// cycles; see the comment at the expansion. Columns of a one-cycle row (hex):
//   op in_valid bit noise exp_sym exp_valid exp_bit data ref_bit last mode goal a b c d
//   op    0 normal cycle, 1 reset cycle, 2 judgment of the counted errors (idle cycle)
//   noise error pattern of the channel for this symbol, {c0, c1}
//   exp_sym   clean symbol the encoder must show in this cycle (checked when in_valid)
//   exp_valid, exp_bit   decoder outputs expected after this clock edge
//   data      this output is an information bit; ref_bit is the bit that was sent
//   last      this output is the last information bit of its frame
//   mode      0 compare out_bit with exp_bit, 1 only count errors against ref_bit
//   goal      coverage goal credited when the row passes (0 none)
//   a b c d   for op 2: allowed bit errors [a, b] and allowed frame errors [c, d]
// The bench never waits for the design, so it has no timeout of its own.
module fec_ber_tb;
    parameter DEPTH = 16, MUTATION = 0;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, in_valid = 0, in_bit = 0;
    reg [1:0] noise = 0;
    wire [1:0] tx_sym, rx_sym;
    wire out_valid, out_bit;

    conv_encoder #(.MUTATION(MUTATION)) encoder(
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_bit(in_bit), .out_sym(tx_sym));
    assign rx_sym = tx_sym ^ noise;
    viterbi_decoder #(.DEPTH(DEPTH), .MUTATION(MUTATION)) decoder(
        .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .in_sym(rx_sym),
        .out_valid(out_valid), .out_bit(out_bit));

    reg [127:0] eo, ev, eu, en, es, ex, eb, ed, er, el, em, eg, ea, ebh, ec, edh;
    reg [127:0] f_data, f_n0, f_n1, f_s0, f_s1, f_expected, f_mode, f_goal;
    integer fd, rc, checks = 0, cycles = 0, f_length, k, j;
    integer bits = 0, bit_errors = 0, frames = 0, frame_errors = 0, in_frame = 0;
    reg [31:0] seen = 0;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d op=%0d valid=%b bit=%b expected valid=%b bit=%b errors=%0d frame_errors=%0d",
                   checks, eo, out_valid, out_bit, ex[0], eb[0], bit_errors, frame_errors);
        end
    endtask

    task credit(input [127:0] goal);
        begin
            if (goal > 31) $fatal(1, "unknown goal");
            if (goal != 0 && !seen[goal[4:0]]) begin
                seen[goal[4:0]] = 1;
                case (goal)
                    1:  $display("COVER roundtrip/clean-frame");
                    2:  $display("COVER roundtrip/gaps-in-valid");
                    3:  $display("COVER roundtrip/continuous-frames");
                    4:  $display("COVER encode/all-transitions");
                    5:  $display("COVER correct/single-c0");
                    6:  $display("COVER correct/single-c1");
                    7:  $display("COVER correct/double-same-symbol");
                    8:  $display("COVER correct/double-adjacent");
                    9:  $display("COVER correct/double-apart");
                    10: $display("COVER beyond/three-errors-miscorrected");
                    11: $display("COVER reset/mid-frame");
                    12: $display("COVER reset/restart-decodes");
                    13: $display("COVER latency/silent-before-depth");
                    14: $display("COVER latency/first-output");
                    15: $display("COVER noise/bit-exact-frame");
                    16: $display("COVER stat/bit-errors-within-interval");
                    17: $display("COVER stat/frame-errors-within-interval");
                    18: $display("COVER tie/lower-predecessor-wins");
                    19: $display("COVER roundtrip/long-stream-with-errors");
                    20: $display("COVER tie/lowest-best-state");
                    default: $fatal(1, "unknown goal");
                endcase
            end
        end
    endtask

    // One clock cycle from the sixteen column registers.
    task one_cycle;
        begin
            rst_n = eo != 1; in_valid = ev[0]; in_bit = eu[0]; noise = en[1:0];
            #1;
            if (in_valid && tx_sym !== es[1:0]) fail("FEC_ENCODE");
            @(posedge clk); #1;
            if (out_valid !== ex[0]) fail("FEC_VALID");
            if (out_valid) begin
                if (out_bit === 1'bx || out_bit === 1'bz) fail("FEC_UNKNOWN");
                if (em == 0 && out_bit !== eb[0]) fail("FEC_DECODE");
                if (ed[0]) begin
                    bits = bits + 1;
                    if (out_bit !== er[0]) begin bit_errors = bit_errors + 1; in_frame = in_frame + 1; end
                    if (el[0]) begin
                        frames = frames + 1;
                        if (in_frame != 0) frame_errors = frame_errors + 1;
                        // A goal on the last bit of a frame speaks about the whole frame.
                        if (eg == 10 && in_frame == 0) $fatal(1, "goal 10 needs a miscorrected frame");
                        if (eg != 0 && eg != 10 && eg != 20 && in_frame != 0) $fatal(1, "goal on a frame with errors");
                        in_frame = 0;
                    end
                end
            end
            if (eo == 1) in_frame = 0;
            if (eo == 2) begin
                // Frames are independent trials; the frame count is judged first.
                if (frame_errors < ec || frame_errors > edh) fail("FEC_FER");
                credit(17);
                if (bit_errors < ea || bit_errors > ebh) fail("FEC_BER");
                credit(16);
            end
            credit(eg);
            cycles = cycles + 1;
            // A statistical case has tens of thousands of cycles; its waveform keeps the first 2000.
            if (em == 1 && cycles == 2000) $dumpoff;
            @(negedge clk);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "VECTORS required");
        if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, fec_ber_tb); end
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        repeat (2) @(negedge clk);   // known reset before the first row
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                         eo, ev, eu, en, es, ex, eb, ed, er, el, em, eg, ea, ebh, ec, edh);
            if (rc != 16) $fatal(1, "malformed vector");
            if (eo == 3) begin
                // A whole frame in one row. The decoder must have just been reset. Columns:
                //   3 length data noise_c0 noise_c1 sym_c0 sym_c1 expected_bits - - mode goal
                // Bit i of a mask belongs to symbol i (or to output i for expected_bits).
                // The row expands to length + 2 + DEPTH - 1 symbols and one reset cycle.
                f_length = ev[31:0]; f_data = eu; f_n0 = en; f_n1 = es; f_s0 = ex; f_s1 = eb; f_expected = ed;
                f_mode = em; f_goal = eg;
                if (f_length < 1 || f_length + 2 + DEPTH - 1 > 128) $fatal(1, "malformed frame row");
                for (k = 0; k < f_length + 2 + DEPTH - 1; k = k + 1) begin
                    j = k - (DEPTH - 1);          // index of the bit that leaves after this symbol
                    eo = 0; ev = 1; eu = k < f_length ? f_data[k] : 0;
                    en = {f_n0[k], f_n1[k]}; es = {f_s0[k], f_s1[k]};
                    ex = j >= 0; eb = j >= 0 ? f_expected[j] : 0;
                    ed = j >= 0 && j < f_length; er = ed[0] ? f_data[j] : 0; el = j == f_length - 1;
                    em = f_mode; eg = el[0] ? f_goal : 0;
                    ea = 0; ebh = 0; ec = 0; edh = 0;
                    one_cycle;
                end
                eo = 1; ev = 0; eu = 0; en = 0; es = 0; ex = 0; eb = 0; ed = 0; er = 0; el = 0; eg = 0;
                one_cycle;
            end else begin
                if (eo > 2 || (eo != 0 && (ev[0] || ex[0]))) $fatal(1, "malformed operation");
                one_cycle;
            end
            checks = checks + 1;
        end
        $fclose(fd);
        $display("COUNT bits=%0d", bits);
        $display("COUNT bit_errors=%0d", bit_errors);
        $display("COUNT frames=%0d", frames);
        $display("COUNT frame_errors=%0d", frame_errors);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
