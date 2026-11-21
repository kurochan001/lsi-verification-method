// CIC decimator: STAGES integrators at the input rate, a decimation by RATE, and STAGES combs
// with a delay of DELAY output samples. No multipliers and no pruning: every register has the
// full output width, so integrators may wrap and the two's-complement result is still exact.
//
// sync is a synchronous restart: it discards the history and the sample offered in the same
// cycle, and makes the next accepted sample the first one of a decimation period.
module cic_decimator #(
    parameter IN_W = 8,
    parameter STAGES = 3,
    parameter RATE = 4,
    parameter DELAY = 1,
    parameter MUTATION = 0,
    // Largest magnitude of the sum is 2**(IN_W-1) * (RATE*DELAY)**STAGES.
    localparam GAIN = (RATE * DELAY) ** STAGES,
    localparam OUT_W = IN_W + $clog2(GAIN)
) (
    input  wire                    clk,
    input  wire                    rst_n,
    input  wire                    in_valid,
    input  wire                    sync,
    input  wire signed [IN_W-1:0]  in_data,
    output reg                     out_valid,
    output reg  signed [OUT_W-1:0] out_data
);
    localparam CNT_W = (RATE > 1) ? $clog2(RATE) : 1;
    localparam [CNT_W-1:0] LAST = CNT_W'(RATE - 1);
    // Mutation 4 starts one sample late in the decimation period.
    localparam [CNT_W-1:0] FIRST = (MUTATION == 4) ? CNT_W'(1) : CNT_W'(0);
    // Mutation 3 reads the comb delay line one position early when it has more than one.
    localparam TAP = (MUTATION == 3 && DELAY > 1) ? DELAY - 2 : DELAY - 1;

    reg signed [OUT_W-1:0] integ [0:STAGES-1];
    reg signed [OUT_W-1:0] line [0:STAGES*DELAY-1];
    reg [CNT_W-1:0] count;

    reg signed [OUT_W-1:0] sum [0:STAGES-1];
    reg signed [OUT_W-1:0] diff [0:STAGES-1];
    reg signed [OUT_W-1:0] term;
    reg signed [OUT_W:0] wide;
    integer i, j;

    // A register one bit narrower than the output: keep the low bits and repeat their sign.
    function automatic signed [OUT_W-1:0] narrow(input signed [OUT_W-1:0] value);
        narrow = {value[OUT_W-2], value[OUT_W-2:0]};
    endfunction

    always @* begin
        for (i = 0; i < STAGES; i = i + 1) begin
            term = (i == 0) ? OUT_W'(in_data) : sum[i-1];
            wide = {integ[i][OUT_W-1], integ[i]} + {term[OUT_W-1], term};
            sum[i] = wide[OUT_W-1:0];                               // wraps, on purpose
            if (MUTATION == 2 && wide[OUT_W] != wide[OUT_W-1])      // mutation 2 clips instead
                sum[i] = wide[OUT_W] ? {1'b1, {(OUT_W-1){1'b0}}} : {1'b0, {(OUT_W-1){1'b1}}};
            if (MUTATION == 1 || (MUTATION == 7 && i == 0)) sum[i] = narrow(sum[i]);
        end
        for (i = 0; i < STAGES; i = i + 1) begin
            term = (i == 0) ? sum[STAGES-1] : diff[i-1];
            diff[i] = term - ((MUTATION == 3 && DELAY == 1) ? {OUT_W{1'b0}} : line[i*DELAY+TAP]);
            if (MUTATION == 1) diff[i] = narrow(diff[i]);
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            out_data <= {OUT_W{1'b0}};
            count <= FIRST;
            for (i = 0; i < STAGES; i = i + 1) integ[i] <= {OUT_W{1'b0}};
            for (i = 0; i < STAGES*DELAY; i = i + 1) line[i] <= {OUT_W{1'b0}};
        end else begin
            out_valid <= 1'b0;
            if (sync) begin
                if (MUTATION != 5) count <= FIRST;                  // mutation 5 keeps the old phase
                for (i = 0; i < STAGES; i = i + 1) integ[i] <= {OUT_W{1'b0}};
                for (i = 0; i < STAGES*DELAY; i = i + 1) line[i] <= {OUT_W{1'b0}};
            end else begin
                if (in_valid || MUTATION == 6)                      // mutation 6 integrates idle cycles
                    for (i = 0; i < STAGES; i = i + 1) integ[i] <= sum[i];
                if (in_valid) begin
                    if (count == LAST) begin
                        count <= {CNT_W{1'b0}};
                        out_valid <= 1'b1;
                        out_data <= diff[STAGES-1];
                        for (i = 0; i < STAGES; i = i + 1) begin
                            line[i*DELAY] <= (i == 0) ? sum[STAGES-1] : diff[i-1];
                            for (j = 1; j < DELAY; j = j + 1) line[i*DELAY+j] <= line[i*DELAY+j-1];
                        end
                    end else begin
                        count <= count + 1'b1;
                    end
                end
            end
        end
    end
endmodule
