// The OTP controller with a lifecycle loader in front of the register block of the lifecycle
// example (examples/local-secure-lifecycle, used unchanged).
//
// Words 0, 1 and 2 of the OTP are the lifecycle: programming word i moves the device one stage
// on. A stage counts as programmed when any bit of any copy is set, so a write that the power
// cut short after one copy already counts: the device can only move towards the restrictive
// side. After every reset the loader reads the three words, and until it has, the register block
// is held in reset and the host cannot use the OTP. The stages give the lifecycle input of the
// register block, where only 0 (TEST) allows the keys to be written:
//   none -> 0 (TEST); word 0 -> 1; words 0, 1 -> 2; words 0, 1, 2 -> 3; any other pattern -> 3.
module otp_lifecycle_top #(
    parameter MUTATION = 0,
    parameter NW = 16,
    parameter WB = 8,
    parameter PROG = 3,
    parameter AW = $clog2(NW)
) (
    input  wire          clk,
    input  wire          rst_n,
    // the host port of the OTP, usable once the lifecycle is loaded
    input  wire          req_valid,
    input  wire          req_write,
    input  wire [AW-1:0] req_addr,
    input  wire [WB-1:0] req_wdata,
    output wire          req_ready,
    output wire          resp_valid,
    output wire [WB-1:0] resp_data,
    output wire [WB-1:0] resp_any,
    output wire          resp_err,
    output wire          resp_corrected,
    output wire          resp_locked,
    // the cell array
    output wire [AW-1:0] cell_word,
    output wire [1:0]    cell_row,
    input  wire [WB-1:0] cell_rdata,
    output wire          prog_en,
    output wire [WB-1:0] prog_mask,
    // the lifecycle
    output reg           lc_ready,
    output reg  [1:0]    lc_state,
    // the register block of the lifecycle example
    input  wire          cs,
    input  wire          we,
    input  wire          re,
    input  wire [7:0]    addr,
    input  wire [31:0]   wdata,
    input  wire          secure,
    input  wire [15:0]   debug_key,
    input  wire          tamper,
    output wire [31:0]   rdata,
    output wire          error,
    output wire          irq
);
    reg [1:0] ld_word;      // the lifecycle word the loader reads next
    reg       ld_pending;   // a read of the loader has been taken and not answered
    reg [1:0] stage;        // words 0 and 1, once read
    wire      ctrl_ready, ctrl_valid;

    wire ld_valid = !lc_ready && !ld_pending;
    assign ctrl_valid = lc_ready ? req_valid : ld_valid;
    assign req_ready = lc_ready && ctrl_ready;

    wire          c_resp_valid;
    otp_ctrl #(.MUTATION(MUTATION), .NW(NW), .WB(WB), .PROG(PROG)) ctrl(
        .clk(clk), .rst_n(rst_n),
        .req_valid(ctrl_valid), .req_write(lc_ready && req_write),
        .req_addr(lc_ready ? req_addr : {{AW-2{1'b0}}, ld_word}), .req_wdata(req_wdata),
        .req_ready(ctrl_ready),
        .resp_valid(c_resp_valid), .resp_data(resp_data), .resp_any(resp_any), .resp_err(resp_err),
        .resp_corrected(resp_corrected), .resp_locked(resp_locked),
        .cell_word(cell_word), .cell_row(cell_row), .cell_rdata(cell_rdata),
        .prog_en(prog_en), .prog_mask(prog_mask));
    assign resp_valid = c_resp_valid && lc_ready;

    // Mutation 7: a stage counts only when the majority of the copies is set, so a lifecycle write
    // cut short after one copy leaves the device in the earlier, less restrictive stage.
    wire programmed = MUTATION == 7 ? |resp_data : |resp_any;
    wire [2:0] stages = {programmed, stage[1:0]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lc_ready <= 1'b0; lc_state <= 2'd3; ld_word <= 2'd0; ld_pending <= 1'b0; stage <= 2'b00;
        end else if (!lc_ready) begin
            if (ld_valid && ctrl_ready) ld_pending <= 1'b1;
            if (c_resp_valid) begin
                ld_pending <= 1'b0;
                if (ld_word != 2'd2) stage[ld_word[0]] <= programmed;
                if (ld_word == 2'd2) begin
                    lc_ready <= 1'b1;
                    case (stages)
                        3'b000: lc_state <= 2'd0;
                        3'b001: lc_state <= 2'd1;
                        3'b011: lc_state <= 2'd2;
                        default: lc_state <= 2'd3;   // 3'b111, and every pattern with a gap
                    endcase
                end else begin
                    ld_word <= ld_word + 1'b1;
                end
            end
        end
    end

    secure_lifecycle regs(
        .clk(clk), .rst_n(rst_n && lc_ready),
        .cs(cs), .we(we), .re(re), .addr(addr), .wdata(wdata), .secure(secure),
        .lifecycle(lc_state), .debug_key(debug_key), .tamper(tamper),
        .rdata(rdata), .error(error), .irq(irq));
endmodule
