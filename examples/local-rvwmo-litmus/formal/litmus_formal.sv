// One SB program per reset. Both stores issue on the first active edge.
// The following edge executes FENCE (or a bubble in the relaxed program).
// Each load may then be requested at any time, independently of the other.
module litmus_program #(parameter FENCED=1, MUTATION=0)(
    input wire clk, read_req0, read_req1,
    output wire x, y, vis0, vis1, done0, done1, r0, r1
);
    reg [2:0] history = 0;
    always @(posedge clk) history <= {history[1:0], 1'b1};
    wire rst_n = history[0];
    wire store = history[0] && !history[1];
    wire fence = FENCED && history[1] && !history[2];
    litmus #(.DRAIN(2), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .issue0(store), .issue1(store),
        .fence0(fence), .fence1(fence),
        .read0(history[2] && read_req0), .read1(history[2] && read_req1),
        .x(x), .y(y), .vis0(vis0), .vis1(vis1),
        .done0(done0), .done1(done1), .r0(r0), .r1(r1)
    );
endmodule

module litmus_formal(input wire clk, read_req0, read_req1);
    wire x, y, vis0, vis1, done0, done1, r0, r1;
    litmus_program #(.FENCED(1), .MUTATION(0)) program_dut(.*);
    // At the fourth edge following initial reset both scheduled stores have
    // published. Prove this invariant to exclude an unreachable forever-empty
    // memory from the induction step when load requests are delayed.
    reg [3:0] elapsed = 0;
    always @(posedge clk) elapsed <= {elapsed[2:0], 1'b1};
    always @(posedge clk) if (elapsed[0]) begin
        ap_publication: assert(!elapsed[3] || (x && y));
        ap_vis0_x: assert(!vis0 || x);
        ap_vis1_y: assert(!vis1 || y);
        ap_no_both_zero: assert(!(done0 && done1 && !r0 && !r1));
        cv_finish: cover(done0 && done1 && r0 && r1);
    end
endmodule

module litmus_formal_relaxed(input wire clk, read_req0, read_req1);
    wire x, y, vis0, vis1, done0, done1, r0, r1;
    litmus_program #(.FENCED(0)) program_dut(.*);
    reg past_reset = 0;
    always @(posedge clk) past_reset <= 1;
    always @(posedge clk) if (past_reset) begin
        cv_both_zero: cover(done0 && done1 && !r0 && !r1);
        cv_both_one: cover(done0 && done1 && r0 && r1);
    end
endmodule
