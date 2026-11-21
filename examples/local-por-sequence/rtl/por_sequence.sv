// Detector output in, synchronised reset and start-up sequence out.
module por_sequence #(parameter STAGES = 2, WAIT = 4, CAL_TIMEOUT = 8, MUTATION = 0)(
    input  wire       clk,
    input  wire       pwr_ok,
    input  wire [3:0] strap,
    input  wire       cal_done,
    input  wire       flag_clr,
    output wire       rst_n,
    output wire       cfg_load,
    output wire       cal_start,
    output wire       ready,
    output wire       init_fail,
    output wire [3:0] cfg,
    output wire       por_flag
);
    por_reset_sync #(.STAGES(STAGES), .MUTATION(MUTATION)) u_sync (.clk(clk), .pwr_ok(pwr_ok), .rst_n(rst_n));
    por_init_ctrl #(.WAIT(WAIT), .CAL_TIMEOUT(CAL_TIMEOUT), .MUTATION(MUTATION)) u_ctrl (
        .clk(clk), .rst_n(rst_n), .strap(strap), .cal_done(cal_done), .flag_clr(flag_clr),
        .cfg_load(cfg_load), .cal_start(cal_start), .ready(ready), .init_fail(init_fail), .cfg(cfg), .por_flag(por_flag));
endmodule
