// Continuous health tests for a binary noise source: the repetition count test (RCT) and the
// adaptive proportion test (APT), with a start-up test and output suppression after a failure.
//
// Each accepted sample (in_valid) updates both tests. A failure sets a sticky flag; the sample
// that fails a test and every later sample are not passed to the output. After reset or a
// restart, the first STARTUP samples are tested but never output; ready rises after them only
// if none of them failed a test. A restart (one-cycle pulse) clears the tests like a reset.
//
// The cutoffs are parameters; how they follow from the false alarm rate is in the README.
module trng_health #(parameter W = 64, RCT_CUTOFF = 9, APT_CUTOFF = 40, STARTUP = 64, MUTATION = 0) (
    input clk,
    input rst_n,
    input restart,
    input in_valid,
    input in_bit,
    output reg out_valid,
    output reg out_bit,
    output reg ready,
    output reg rct_fail,
    output reg apt_fail,
    output alarm
);
    localparam integer RW = $clog2(RCT_CUTOFF + 1);
    localparam integer CW = $clog2(W + 2);
    localparam integer PW = $clog2(W + 1);
    localparam integer SW = $clog2(STARTUP + 1);
    // MUTATION 1: the RCT fails one repetition early; 2: the APT one match late;
    // 7: the APT window is one sample longer.
    localparam integer R_AT = MUTATION == 1 ? RCT_CUTOFF - 1 : RCT_CUTOFF;
    localparam integer A_AT = MUTATION == 2 ? APT_CUTOFF + 1 : APT_CUTOFF;
    localparam integer P_LAST = MUTATION == 7 ? W : W - 1;
    localparam [RW-1:0] RCAP = RCT_CUTOFF[RW-1:0];
    localparam [RW-1:0] RHIT = R_AT[RW-1:0];
    localparam [CW-1:0] AHIT = A_AT[CW-1:0];
    localparam [PW-1:0] PLAST = P_LAST[PW-1:0];
    localparam [SW-1:0] SDONE = STARTUP[SW-1:0];
    localparam [SW-1:0] SLAST = SDONE - 1'b1;

    reg have_last, last_bit;
    reg [RW-1:0] run;
    reg [PW-1:0] pos;
    reg ref_bit;
    reg [CW-1:0] cnt;
    reg [SW-1:0] seen;

    // Repetition count: length of the run of equal samples, saturated at the cutoff.
    wire same = have_last && in_bit == last_bit;
    wire [RW-1:0] run_next = !same ? {{(RW-1){1'b0}}, 1'b1} : (run >= RCAP ? run : run + 1'b1);
    wire rct_hit = in_valid && run_next >= RHIT;
    // Adaptive proportion: occurrences of the window's first sample within the window.
    wire window_start = pos == {PW{1'b0}};
    wire [CW-1:0] cnt_next = window_start ? {{(CW-1){1'b0}}, 1'b1} : (in_bit == ref_bit ? cnt + 1'b1 : cnt);
    wire apt_hit = in_valid && cnt_next >= AHIT;
    wire failed = rct_fail || apt_fail || rct_hit || apt_hit;
    assign alarm = rct_fail || apt_fail;

    always @(posedge clk) begin
        if (!rst_n || restart) begin
            out_valid <= 1'b0;
            out_bit <= 1'b0;
            ready <= MUTATION == 6;                       // 6: no start-up test
            rct_fail <= 1'b0;
            apt_fail <= 1'b0;
            seen <= {SW{1'b0}};
            if (!rst_n || MUTATION != 3) begin            // 3: a restart keeps the RCT state
                have_last <= 1'b0;
                last_bit <= 1'b0;
                run <= {RW{1'b0}};
            end
            if (!rst_n || MUTATION != 4) begin            // 4: a restart keeps the APT window
                pos <= {PW{1'b0}};
                ref_bit <= 1'b0;
                cnt <= {CW{1'b0}};
            end
        end else begin
            out_valid <= in_valid && ready && (!failed || MUTATION == 5);   // 5: output after a failure
            out_bit <= in_bit;
            if (in_valid) begin
                have_last <= 1'b1;
                last_bit <= in_bit;
                run <= run_next;
                pos <= pos == PLAST ? {PW{1'b0}} : pos + 1'b1;
                if (window_start) ref_bit <= in_bit;
                cnt <= cnt_next;
                if (rct_hit) rct_fail <= 1'b1;
                if (apt_hit) apt_fail <= 1'b1;
                if (seen != SDONE) seen <= seen + 1'b1;
                if (seen == SLAST && !failed) ready <= 1'b1;
            end else if (MUTATION == 8) begin
                have_last <= 1'b0;                        // 8: an idle cycle ends the run
            end
        end
    end
endmodule
