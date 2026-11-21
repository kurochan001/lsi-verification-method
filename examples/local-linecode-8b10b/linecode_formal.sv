// Proof harness for the encoder and the decoder.
//   forward    whatever the encoder sends, the decoder returns the same character without an error
//   backward   whatever code the decoder accepts for a running disparity, the encoder sends exactly
//              that code for the decoded character and that disparity (free_code and free_rd are
//              unconstrained inputs, so this covers all 1024 codes in both disparities)
//   line       disparity of each code and of the stream, longest run inside a code and across two
//              codes, and where the comma can appear
// The previous character is kept as (data, k, disparity before it); the auxiliary assertion
// ai_previous states that the kept code and the encoder's present disparity are what the encoder
// gives for it. It is proved, not assumed, and makes the two-code properties inductive.
// SIDE selects the properties: 0 all, 1 forward and line only, 2 backward only.
module linecode_formal #(parameter MUTATION = 0, SIDE = 0) (
    input wire clk, rst_n, valid, k,
    input wire [7:0] data,
    input wire [9:0] free_code,
    input wire free_rd
);
    wire [9:0] code;
    wire k_err, enc_rd;
    enc_8b10b #(.MUTATION(MUTATION)) enc(.clk(clk), .rst_n(rst_n), .valid(valid), .k(k), .data(data),
        .code(code), .k_err(k_err), .rd(enc_rd));
    wire sent = valid && !k_err;
    wire [7:0] got;
    wire got_k, code_err, disp_err, dec_rd;
    dec_8b10b #(.MUTATION(MUTATION)) dec(.clk(clk), .rst_n(rst_n), .valid(sent), .code(code),
        .data(got), .k(got_k), .code_err(code_err), .disp_err(disp_err), .rd(dec_rd));

    // Any code, any disparity, through the decoder and back through the encoder in both disparities.
    wire [7:0] free_data;
    wire free_k, free_code_err, free_disp_err, free_next;
    dec_8b10b_comb #(.MUTATION(MUTATION)) any_dec(.code(free_code), .rd(free_rd), .data(free_data), .k(free_k),
        .code_err(free_code_err), .disp_err(free_disp_err), .rd_next(free_next));
    wire [9:0] back_code, other_code;
    wire back_next, back_k_err, other_k_err;
    enc_8b10b_comb #(.MUTATION(MUTATION)) back(.data(free_data), .k(free_k), .rd(free_rd),
        .code(back_code), .rd_next(back_next), .k_err(back_k_err));
    enc_8b10b_comb #(.MUTATION(MUTATION)) other(.data(free_data), .k(free_k), .rd(!free_rd),
        .code(other_code), .rd_next(), .k_err(other_k_err));

    // The previous character and what the encoder gives for it.
    reg f_past = 0, prev_valid = 0, prev_k = 0, prev_rd = 0;
    reg [7:0] prev_data = 0;
    reg [9:0] prev_code = 0;
    wire [9:0] again_code;
    wire again_next, again_k_err;
    enc_8b10b_comb #(.MUTATION(MUTATION)) again(.data(prev_data), .k(prev_k), .rd(prev_rd),
        .code(again_code), .rd_next(again_next), .k_err(again_k_err));
    always @(posedge clk) begin
        f_past <= 1;
        if (!rst_n) prev_valid <= 0;
        else if (sent) begin
            prev_valid <= 1; prev_k <= k; prev_data <= data; prev_rd <= enc_rd; prev_code <= code;
        end
    end

    function [3:0] ones10(input [9:0] v);
        integer n;
        begin
            ones10 = 0;
            for (n = 0; n < 10; n = n + 1) ones10 = ones10 + {3'b000, v[n]};
        end
    endfunction
    // Longest run of equal bits in the upper `count` bits of v.
    function [4:0] longest(input [19:0] v, input integer count);
        integer n;
        reg [4:0] current;
        begin
            longest = 1; current = 1;
            for (n = 18; n >= 20 - count; n = n - 1) begin
                current = v[n] == v[n + 1] ? current + 5'd1 : 5'd1;
                if (current > longest) longest = current;
            end
        end
    endfunction
    function comma(input [6:0] seven);
        comma = seven == 7'b0011111 || seven == 7'b1100000;
    endfunction
    function inner_comma(input [19:0] v);   // a comma that starts at bits 1 to 9 of twenty
        integer n;
        begin
            inner_comma = 0;
            for (n = 1; n <= 9; n = n + 1) if (comma(v[19 - n -: 7])) inner_comma = 1;
        end
    endfunction

    wire [4:0] x = data[4:0];
    wire legal_k = x == 5'd28 || (data[7:5] == 3'd7 && (x == 5'd23 || x == 5'd27 || x == 5'd29 || x == 5'd30));
    wire comma_char = k && (data == 8'h3C || data == 8'hBC || data == 8'hFC);
    wire [3:0] weight = ones10(code);
    wire [3:0] free_weight = ones10(free_code);
    wire [19:0] pair = {prev_code, code};
    wire prev_k28_7 = prev_k && prev_data == 8'hFC;

    always @(posedge clk) if (!f_past) as_initial_reset: assume(!rst_n);

    generate
        if (SIDE != 2) begin : g_forward
            always @(posedge clk) if (f_past) begin
                ai_rd_equal: assert(enc_rd == dec_rd);
                ai_previous: assert(prev_valid ? (!again_k_err && prev_code == again_code && enc_rd == again_next)
                                               : !enc_rd);
                if (valid) ap_k_err: assert(k_err == (k && !legal_k));
                if (sent) begin
                    ap_roundtrip: assert(got == data && got_k == k && !code_err && !disp_err);
                    ap_disparity: assert(weight == 4'd5 || (weight == 4'd6 && !enc_rd) || (weight == 4'd4 && enc_rd));
                    ap_run: assert(longest({code, 10'd0}, 10) <= 5'd5 && (!prev_valid || longest(pair, 20) <= 5'd5));
                    ap_comma: assert(comma(code[9:3]) == comma_char && !comma(code[8:2]) && !comma(code[7:1]) &&
                                     !comma(code[6:0]) && (!prev_valid || prev_k28_7 || !inner_comma(pair)));
                end
                if ($past(rst_n && sent))
                    ap_rd_step: assert(enc_rd == ($past(weight) == 4'd5 ? $past(enc_rd) : $past(weight) == 4'd6));
                cp_comma_minus: cover(sent && code == 10'b0011111010);
                cp_comma_plus: cover(sent && code == 10'b1100000101);
                cp_d7_plus: cover(sent && !k && code[9:4] == 6'b000111);
                cp_alternate_7: cover(sent && !k && code[3:0] == 4'b0111);
                cp_run_across: cover(sent && prev_valid && longest(pair, 20) == 5'd5 &&
                                     longest({code, 10'd0}, 10) < 5'd5 && longest({prev_code, 10'd0}, 10) < 5'd5);
                cp_false_comma: cover(sent && prev_valid && prev_k28_7 && inner_comma(pair));
            end
        end
        if (SIDE != 1) begin : g_backward
            always @(posedge clk) if (f_past) begin
                if (!free_code_err && !free_disp_err)
                    ap_accept: assert(!back_k_err && back_code == free_code && back_next == free_next);
                if (free_disp_err)
                    ap_other: assert(!free_code_err && !other_k_err && other_code == free_code);
                ap_dec_rd: assert(free_next == (free_weight == 4'd5 ? free_rd : free_weight > 4'd5));
                cp_disparity_error: cover(free_disp_err);
                cp_balanced_reject: cover(free_code_err && free_weight == 4'd5);
            end
        end
    endgenerate
endmodule
