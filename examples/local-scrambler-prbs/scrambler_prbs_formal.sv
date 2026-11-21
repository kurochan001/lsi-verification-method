// Proof harness: the same module at one bit per clock and at W bits per clock.
// A word and its valid flag are held for W clocks. The serial instance takes bit `phase` of
// the word on every clock; the parallel instance takes the whole word on the last clock.
// The serial outputs of the W clocks are collected and compared with the parallel word, and
// at every word boundary the two instances must hold the same state. MUTATION goes to the
// parallel instance only.
//   TARGET 0 PRBS generator, 1 scrambler, 2 descrambler, 3 PRBS checker.
module scrambler_prbs_formal #(parameter TARGET = 0, N = 7, TAP = 6, W = 8, MUTATION = 0) (
    input wire clk, rst_n,
    input wire [W-1:0] next_word,
    input wire next_valid, next_load,
    input wire [N-1:0] next_seed
);
    localparam PW = $clog2(W);
    localparam [PW-1:0] LAST = W - 1;
    reg [PW-1:0] phase;
    reg [W-1:0] word;
    reg valid, load;
    reg [N-1:0] seed;
    wire last = phase == LAST;
    always @(posedge clk) begin
        if (!rst_n) phase <= 0;
        else phase <= last ? {PW{1'b0}} : phase + 1'b1;
        if (!rst_n || last) begin
            word <= next_word; valid <= next_valid; load <= next_load; seed <= next_seed;
        end
    end

    wire serial_bit;           // the output of the serial instance on this clock
    wire [W-1:0] parallel;     // the output word of the parallel instance
    wire same_state;
    generate
        if (TARGET == 0) begin : g_gen
            wire [N-1:0] sa, sb;
            wire za, zb;
            prbs_gen #(.N(N), .TAP(TAP), .W(1)) serial(
                .clk(clk), .rst_n(rst_n), .enable(valid), .seed_load(load && last), .seed(seed),
                .data(serial_bit), .zero(za), .f_state(sa));
            prbs_gen #(.N(N), .TAP(TAP), .W(W), .MUTATION(MUTATION)) wide(
                .clk(clk), .rst_n(rst_n), .enable(valid && last), .seed_load(load && last), .seed(seed),
                .data(parallel), .zero(zb), .f_state(sb));
            assign same_state = sa == sb && za == zb;
        end else if (TARGET == 1) begin : g_scr
            wire [N-1:0] sa, sb;
            ss_scrambler #(.N(N), .TAP(TAP), .W(1)) serial(
                .clk(clk), .rst_n(rst_n), .valid(valid), .din(word[phase]), .dout(serial_bit), .f_state(sa));
            ss_scrambler #(.N(N), .TAP(TAP), .W(W), .MUTATION(MUTATION)) wide(
                .clk(clk), .rst_n(rst_n), .valid(valid && last), .din(word), .dout(parallel), .f_state(sb));
            assign same_state = sa == sb;
        end else if (TARGET == 2) begin : g_dsc
            wire [N-1:0] sa, sb;
            ss_descrambler #(.N(N), .TAP(TAP), .W(1)) serial(
                .clk(clk), .rst_n(rst_n), .valid(valid), .din(word[phase]), .dout(serial_bit), .f_state(sa));
            ss_descrambler #(.N(N), .TAP(TAP), .W(W), .MUTATION(MUTATION)) wide(
                .clk(clk), .rst_n(rst_n), .valid(valid && last), .din(word), .dout(parallel), .f_state(sb));
            assign same_state = sa == sb;
        end else begin : g_chk
            localparam SW = N + $clog2(N + 1) + $clog2(33) + $clog2(9) + 6 + 1;
            wire [SW-1:0] sa, sb;
            wire la, lb, ka, kb;
            wire [5:0] ca, cb;
            wire [W-1:0] flags;
            prbs_check #(.N(N), .TAP(TAP), .W(1), .LOCK(32), .LOSS(8), .CW(6)) serial(
                .clk(clk), .rst_n(rst_n), .valid(valid), .data(word[phase]), .err(serial_bit),
                .locked(la), .count(ca), .stuck(ka), .f_state(sa));
            prbs_check #(.N(N), .TAP(TAP), .W(W), .LOCK(32), .LOSS(8), .CW(6), .MUTATION(MUTATION)) wide(
                .clk(clk), .rst_n(rst_n), .valid(valid && last), .data(word), .err(flags),
                .locked(lb), .count(cb), .stuck(kb), .f_state(sb));
            // The parallel checker reports flags only on its valid clock; an idle word has none.
            assign parallel = valid ? flags : {W{1'b0}};
            assign same_state = sa == sb && la == lb && ca == cb && ka == kb;
        end
    endgenerate

    reg [W-1:0] collected;     // serial outputs of the earlier clocks of this word
    reg f_past = 0, f_ran = 0;
    always @(posedge clk) begin
        f_past <= 1;
        collected[phase] <= serial_bit;
        if (rst_n && valid) f_ran <= 1;
    end
    wire [W-1:0] serial_word = (collected & ~({{(W-1){1'b0}}, 1'b1} << phase)) | ({{(W-1){1'b0}}, serial_bit} << phase);

    always @(posedge clk) begin
        if (!f_past) as_initial_reset: assume(!rst_n);
        if (f_past && rst_n && $past(rst_n)) begin
            if (phase == 0) ai_state: assert(same_state);
            if (last && valid) ap_word: assert(serial_word == parallel);   // an idle word has no output bits
            cp_word: cover(last && valid && parallel != 0);
            cp_idle_word: cover(last && !valid && f_ran);
            cp_two_words: cover(last && valid && $past(valid, W) && $past(last, W));
        end
        if (f_past) cp_reset_after_run: cover(!rst_n && f_ran);
    end
endmodule
