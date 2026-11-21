// Formal checks for reset_x_unit. Nothing is assumed about the first state: no register of the
// design has an initial value here, and no reset is assumed at the start. Every check waits
// for the first clock edge with rst high (f_seen).
//
// VALUES = 0: two copies get the same inputs and start from independent, arbitrary register
//             values. What must be known after a reset has to be equal in both copies.
// VALUES = 1: one copy is compared with values: the reset values, the time of ready, and a
//             small model that starts from defined values.
// The two sets are separate because two copies with the same wrong reset value still agree.
module reset_x_formal #(
    parameter WIDTH = 4,
    parameter STAGES = 3,
    parameter MUTATION = 0,
    parameter VALUES = 0
) (
    input wire             clk,
    input wire             rst,
    input wire             in_valid,
    input wire [WIDTH-1:0] in_data,
    input wire             cfg_we,
    input wire             cfg_step2
);
    localparam CW = $clog2(STAGES);
    localparam integer FLUSH_I = STAGES - 1;
    localparam [CW-1:0] FLUSH = FLUSH_I[CW-1:0];

    wire                    a_ready, a_valid, a_odd, a_err, a_step;
    wire [WIDTH-1:0]        a_data;
    wire [3:0]              a_count;
    wire [STAGES-1:0]       a_v;
    wire [STAGES*WIDTH-1:0] a_d;
    wire [CW-1:0]           a_init;
    wire                    b_ready, b_valid, b_odd, b_err, b_step;
    wire [WIDTH-1:0]        b_data;
    wire [3:0]              b_count;
    wire [STAGES-1:0]       b_v;
    wire [STAGES*WIDTH-1:0] b_d;
    wire [CW-1:0]           b_init;

    reset_x_unit #(.WIDTH(WIDTH), .STAGES(STAGES), .MUTATION(MUTATION)) a(
        .clk(clk), .rst(rst), .in_valid(in_valid), .in_data(in_data), .cfg_we(cfg_we), .cfg_step2(cfg_step2),
        .ready(a_ready), .out_valid(a_valid), .out_data(a_data), .odd(a_odd), .count(a_count), .err(a_err),
        .stage_valid_o(a_v), .stage_data_o(a_d), .init_o(a_init), .step_o(a_step));
    reset_x_unit #(.WIDTH(WIDTH), .STAGES(STAGES), .MUTATION(MUTATION)) b(
        .clk(clk), .rst(rst), .in_valid(in_valid), .in_data(in_data), .cfg_we(cfg_we), .cfg_step2(cfg_step2),
        .ready(b_ready), .out_valid(b_valid), .out_data(b_data), .odd(b_odd), .count(b_count), .err(b_err),
        .stage_valid_o(b_v), .stage_data_o(b_d), .init_o(b_init), .step_o(b_step));

    // Clock edges since the last one with rst high, counted up to the flush length.
    reg          f_seen = 1'b0;
    reg [CW-1:0] f_cnt = {CW{1'b0}};
    always @(posedge clk) begin
        if (rst) begin
            f_seen <= 1'b1;
            f_cnt <= {CW{1'b0}};
        end else if (f_cnt != FLUSH) f_cnt <= f_cnt + 1'b1;
    end

    integer k;
    reg stages_equal, data_equal, stages_model;

    // A model with defined first values, for the value checks.
    reg [STAGES-1:0] m_v = {STAGES{1'b0}};
    reg [3:0]        m_count = 4'd0;
    reg              m_err = 1'b0, m_step = 1'b0;
    wire m_ready = f_seen && f_cnt == FLUSH;
    wire m_valid = m_v[STAGES-1] && m_ready;
    always @(posedge clk) begin
        m_v <= {m_v[STAGES-2:0], in_valid && m_ready && !rst};
        m_step <= rst ? 1'b0 : cfg_we ? cfg_step2 : m_step;
        m_count <= rst ? 4'd0 : m_valid ? m_count + (m_step ? 4'd2 : 4'd1) : m_count;
        m_err <= rst ? 1'b0 : m_err || (in_valid && !m_ready);
    end

    always @* begin
        // Stage j holds something that entered after the reset once j edges have passed.
        stages_equal = 1'b1;
        data_equal = 1'b1;
        stages_model = 1'b1;
        for (k = 0; k < STAGES; k = k + 1) begin
            if (k <= f_cnt) begin
                if (a_v[k] != b_v[k]) stages_equal = 1'b0;
                if (a_v[k] && a_d[k*WIDTH +: WIDTH] != b_d[k*WIDTH +: WIDTH]) data_equal = 1'b0;
                if (a_v[k] != m_v[k]) stages_model = 1'b0;
            end
        end
    end

    generate
        if (VALUES == 0) begin : g_known
            always @(posedge clk) begin
                if (f_seen) begin
                    ap_known_ready:  assert(a_ready == b_ready);
                    ap_known_stream: assert(a_valid == b_valid && (!a_valid || a_data == b_data));
                    ap_known_odd:    assert(a_odd == b_odd);
                    ap_known_count:  assert(a_count == b_count);
                    ap_known_err:    assert(a_err == b_err);
                    ap_known_step:   assert(a_step == b_step);
                    ap_known_stages: assert(stages_equal);
                    ai_known_init:   assert(a_init == f_cnt && b_init == f_cnt);
                    ai_known_data:   assert(data_equal);
                end
            end
        end else begin : g_values
            always @(posedge clk) begin
                if (f_seen) begin
                    if (f_cnt == {CW{1'b0}})
                        ap_reset_values: assert(!a_valid && a_count == 4'd0 && !a_err && !a_step && !a_v[0] && !a_odd);
                    ap_ready_time:  assert(a_ready == (f_cnt == FLUSH));
                    ap_valid_model: assert(a_valid == m_valid);
                    ap_count_model: assert(a_count == m_count);
                    ap_err_model:   assert(a_err == m_err);
                    ai_step_model:  assert(a_step == m_step);
                    ai_init_model:  assert(a_init == f_cnt);
                    ai_stage_model: assert(stages_model);
                end
            end
        end
    endgenerate

    always @(posedge clk) begin
        if (f_seen) begin
            // The unknown data is really there: the copies differ while nothing is valid.
            cp_unknown_data:  cover(!a_valid && a_ready && a_data != b_data);
            cp_first_output:  cover(a_valid);
            cp_refused:       cover(a_err);
            cp_step2:         cover(a_valid && a_step);
            cp_reset_in_flight: cover(rst && a_v != {STAGES{1'b0}} && f_cnt == FLUSH);
        end
    end
endmodule
