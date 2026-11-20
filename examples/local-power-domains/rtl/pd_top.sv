// Always-on domain with the controller, the retention copies, the isolation of the outputs,
// and the two switched domains.
// MUTATION 1: the clamp of a_sum works only while A is powered. 2: a_idle_n is clamped to 0.
module pd_top #(parameter MUTATION = 0, parameter SETTLE = 2) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       req_a,      // requested power of A
    input  wire       req_b,      // requested power of B; B follows only while A is requested
    input  wire       op_valid,
    input  wire       op_sel,     // 0 = A, 1 = B
    input  wire [7:0] op_data,
    output wire       op_ready,
    output wire       a_on,
    output wire       b_on,
    output wire       busy,
    output wire       pwr_a,
    output wire       pwr_b,
    output wire [7:0] a_sum,      // isolated to 0
    output wire       a_idle_n,   // isolated to 1
    output wire [7:0] a_last,     // isolated to the last value
    output wire [7:0] b_count,    // isolated to 0
    output wire [3:0] b_mode      // isolated to the last value
);
    wire iso_a, iso_b, rst_a_n, rst_b_n, save_a, save_b, restore_a, restore_b;
    wire [7:0] a_sum_raw, a_last_raw, b_count_raw;
    wire       a_idle_n_raw;
    wire [3:0] b_mode_raw;
    reg  [7:0] acc_ret, last_hold;
    reg  [3:0] mode_ret, mode_hold;

    pd_ctrl #(.MUTATION(MUTATION), .SETTLE(SETTLE)) u_ctrl (
        .clk(clk), .rst_n(rst_n), .req_a(req_a), .req_b(req_b),
        .pwr_a(pwr_a), .pwr_b(pwr_b), .iso_a(iso_a), .iso_b(iso_b),
        .rst_a_n(rst_a_n), .rst_b_n(rst_b_n), .act_a(a_on), .act_b(b_on),
        .save_a(save_a), .save_b(save_b), .restore_a(restore_a), .restore_b(restore_b),
        .busy(busy));

    assign op_ready = op_sel ? b_on : a_on;

    pd_domain_a #(.MUTATION(MUTATION)) u_a (
        .clk(clk), .rst_n(rst_n & rst_a_n), .op(op_valid & ~op_sel & a_on), .data(op_data),
        .restore(restore_a), .acc_saved(acc_ret),
        .sum(a_sum_raw), .idle_n(a_idle_n_raw), .last(a_last_raw));

    pd_domain_b #(.MUTATION(MUTATION)) u_b (
        .clk(clk), .rst_n(rst_n & rst_b_n), .op(op_valid & op_sel & b_on), .data(op_data),
        .a_bit(a_sum_raw[0]), .restore(restore_b), .mode_saved(mode_ret),
        .count_out(b_count_raw), .mode_out(b_mode_raw));

    // Retention copies and the values held by the isolation, all in the always-on domain.
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc_ret <= 8'd0; mode_ret <= 4'd0; last_hold <= 8'd0; mode_hold <= 4'd0;
        end else begin
            if (save_a) acc_ret <= a_sum_raw;
            if (save_b) mode_ret <= b_mode_raw;
            if (!iso_a) last_hold <= a_last_raw;
            if (!iso_b) mode_hold <= b_mode_raw;
        end
    end

    wire clamp_sum = (MUTATION == 1) ? (iso_a & pwr_a) : iso_a;
    assign a_sum    = clamp_sum ? 8'd0 : a_sum_raw;
    assign a_idle_n = iso_a ? (MUTATION != 2) : a_idle_n_raw;
    assign a_last   = iso_a ? last_hold : a_last_raw;
    assign b_count  = iso_b ? 8'd0 : b_count_raw;
    assign b_mode   = iso_b ? mode_hold : b_mode_raw;
endmodule
