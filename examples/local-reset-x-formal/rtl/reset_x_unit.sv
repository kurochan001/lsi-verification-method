// A small pipeline that mixes registers with and without a reset.
//
// With a reset:    the flush counter, the first valid bit, the step setting, the counter, the error flag.
// Without a reset: the other valid bits (they are flushed through the pipeline) and all data registers.
//
// After the last clock edge with rst high, the design needs STAGES-1 more edges to push the unknown
// valid bits out. It shows ready only then, and it hides the last valid bit until then.
//
// MUTATION 1: the counter has no reset.
// MUTATION 2: the parity output is not qualified by out_valid.
// MUTATION 3: ready rises one cycle early, before the last valid bit is flushed.
// MUTATION 4: the reset of the error flag is skipped while the flush counter is 0 (an if).
// MUTATION 5: the reset of the step setting is skipped while the flush counter is 0 (a case).
//             After any complete reset, 4 and 5 behave like the correct design. They differ only
//             from a power-up value, and simulation from X takes the branch that hides it.
// MUTATION 6: the counter is reset to 1, a known but wrong value.
module reset_x_unit #(
    parameter WIDTH = 8,
    parameter STAGES = 3,
    parameter MUTATION = 0
) (
    input  wire                    clk,
    input  wire                    rst,
    input  wire                    in_valid,
    input  wire [WIDTH-1:0]        in_data,
    input  wire                    cfg_we,
    input  wire                    cfg_step2,
    output wire                    ready,
    output wire                    out_valid,
    output wire [WIDTH-1:0]        out_data,
    output wire                    odd,
    output reg  [3:0]              count,
    output reg                     err,
    // Observation of the registers, for the checks. Not part of the function.
    output wire [STAGES-1:0]       stage_valid_o,
    output wire [STAGES*WIDTH-1:0] stage_data_o,
    output wire [$clog2(STAGES)-1:0] init_o,
    output wire                    step_o
);
    localparam CW = $clog2(STAGES);
    localparam integer FLUSH_I = STAGES - 1;
    localparam integer EARLY_I = STAGES - 2;
    localparam [CW-1:0] FLUSH = FLUSH_I[CW-1:0];
    localparam [CW-1:0] EARLY = EARLY_I[CW-1:0];

    reg [CW-1:0]           init;
    reg                    step;
    reg [STAGES-1:0]       v;
    reg [STAGES*WIDTH-1:0] d;

    assign ready     = init == FLUSH || (MUTATION == 3 && init == EARLY);
    assign out_valid = v[STAGES-1] && ready;
    assign out_data  = d[STAGES*WIDTH-1 -: WIDTH];
    assign odd       = MUTATION == 2 ? ^out_data : out_valid && ^out_data;
    assign stage_valid_o = v;
    assign stage_data_o  = d;
    assign init_o = init;
    assign step_o = step;

    wire accept = in_valid && ready;
    wire refuse = in_valid && !ready && !rst;

    always @(posedge clk) begin
        if (rst) init <= {CW{1'b0}};
        else if (init != FLUSH) init <= init + 1'b1;
    end

    // Only the first valid bit is reset. The others take the bit before them.
    always @(posedge clk) begin
        v[0] <= accept && !rst;
        v[STAGES-1:1] <= v[STAGES-2:0];
    end

    // Data registers have no reset. Each one is written only together with its valid bit.
    genvar g;
    generate
        for (g = 0; g < STAGES; g = g + 1) begin : g_data
            if (g == 0) begin : g_first
                always @(posedge clk) if (accept) d[WIDTH-1:0] <= in_data;
            end else begin : g_next
                always @(posedge clk) if (v[g-1]) d[g*WIDTH +: WIDTH] <= d[(g-1)*WIDTH +: WIDTH];
            end
        end
    endgenerate

    generate
        if (MUTATION == 5) begin : g_step_bug
            always @(posedge clk) begin
                case (init)
                    {CW{1'b0}}: if (cfg_we && !rst) step <= cfg_step2;
                    default: begin
                        if (rst) step <= 1'b0;
                        else if (cfg_we) step <= cfg_step2;
                    end
                endcase
            end
        end else begin : g_step
            always @(posedge clk) begin
                if (rst) step <= 1'b0;
                else if (cfg_we) step <= cfg_step2;
            end
        end
    endgenerate

    wire [3:0] delta = step ? 4'd2 : 4'd1;

    always @(posedge clk) begin
        if (rst && MUTATION != 1) count <= MUTATION == 6 ? 4'd1 : 4'd0;
        else if (out_valid) count <= count + delta;
    end

    // Sticky error: an input was offered while the design was not ready.
    generate
        if (MUTATION == 4) begin : g_err_bug
            always @(posedge clk) begin
                if (rst && init != {CW{1'b0}}) err <= 1'b0;
                else if (err) err <= 1'b1;
                else err <= refuse;
            end
        end else begin : g_err
            always @(posedge clk) begin
                if (rst) err <= 1'b0;
                else if (err) err <= 1'b1;
                else err <= refuse;
            end
        end
    endgenerate
endmodule
