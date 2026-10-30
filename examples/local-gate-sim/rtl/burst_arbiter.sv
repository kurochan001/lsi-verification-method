// Fixed-priority burst arbiter: the lowest-numbered requester wins a four-beat burst,
// one idle cycle follows, and a counter records completed bursts. Every mutation keeps
// RTL simulation correct and changes only what synthesis builds.
module burst_arbiter #(parameter MUTATION = 0) (
    input  wire       clk, rst_n,
    input  wire [3:0] req,
    output reg        out_valid, out_last,
    output reg  [1:0] out_id,
    output reg  [7:0] bursts);
    localparam IDLE = 2'd0, BURST = 2'd1, GAP = 2'd2;
    reg [1:0] state, beat, pick, pick_q;

    // Mutation 3: an FPGA-style power-on reset that counts up from an initial value.
    // ASIC flip-flops have no initial value, so the count never becomes known.
    reg [1:0] por = 2'd0;
    always @(posedge clk) if (por != 2'd3) por <= por + 2'd1;
    wire rst = !rst_n || (MUTATION == 3 && por != 2'd3);

    // Mutation 2: parallel_case tells synthesis that at most one item matches, which is
    // false for a priority encoder. Simulators ignore the comment.
    generate if (MUTATION == 2) begin : g_parallel
        always @* begin
            pick = 2'd0;
            casez (req) // synopsys parallel_case
                4'b???1: pick = 2'd0;
                4'b??1?: pick = 2'd1;
                4'b?1??: pick = 2'd2;
                4'b1???: pick = 2'd3;
            endcase
        end
    end else begin : g_priority
        always @* begin
            pick = 2'd0;
            casez (req)
                4'b???1: pick = 2'd0;
                4'b??1?: pick = 2'd1;
                4'b?1??: pick = 2'd2;
                4'b1???: pick = 2'd3;
            endcase
        end
    end endgenerate

    // Mutation 4: a blocking assignment in a separate clocked block. Icarus runs this block
    // before the one below at each edge, so RTL sees the new value; synthesis builds a register.
    always @(posedge clk) pick_q = pick;

    always @(posedge clk) begin
        if (rst) begin
            state <= IDLE; beat <= 2'd0; out_valid <= 1'b0; out_last <= 1'b0; out_id <= 2'd0;
            if (MUTATION != 1) bursts <= 8'd0;
            // synopsys translate_off
            // Mutation 1: a functional reset placed inside a simulation-only region.
            if (MUTATION == 1) bursts <= 8'd0;
            // synopsys translate_on
        end else case (state)
            IDLE: if (|req) begin
                state <= BURST; beat <= 2'd0; out_valid <= 1'b1;
                out_id <= MUTATION == 4 ? pick_q : pick;
            end
            BURST: begin
                beat <= beat + 2'd1;
                out_last <= beat == 2'd2;
                if (beat == 2'd3) begin
                    state <= GAP; out_valid <= 1'b0; bursts <= bursts + 8'd1;
                end
            end
            default: state <= IDLE;
        endcase
    end
endmodule
