// rv32i_core with DEBUG = 1 (machine mode with traps), with names for the debug signals that the
// core carries above its interrupt line and above its halted bit.
module rv32i_debug_core #(parameter MUTATION = 0, PREDICT = 0) (
    input  wire        clk, rst_n, irq,
    output wire [31:0] imem_addr,
    input  wire [31:0] imem_data,
    output wire        dmem_valid, dmem_we,
    output wire [31:0] dmem_addr, dmem_wdata,
    output wire [3:0]  dmem_be,
    input  wire [31:0] dmem_rdata,
    input  wire        dmem_ready,
    output wire        ret_valid,
    output wire [31:0] ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data,
    output wire [4:0]  ret_rd,
    output wire [1:0]  ret_mem,
    output wire        halted,                    // stopped by the EBREAK that ends the program
    input  wire        dbg_haltreq, dbg_resumereq, dbg_reg_we,
    input  wire [15:0] dbg_regno,
    input  wire [31:0] dbg_reg_wdata,
    output wire        dbg_halted, dbg_reg_known,
    output wire [31:0] dbg_reg_rdata);
    wire [31:0] perf_ctrl, perf_flush;
    rv32i_core #(.MUTATION(MUTATION), .PREDICT(PREDICT), .TRAPS(1), .PRIV(0), .DEBUG(1)) core(
        .clk(clk), .rst_n(rst_n), .irq({dbg_reg_wdata, dbg_regno, dbg_reg_we, dbg_resumereq, dbg_haltreq, irq}),
        .imem_addr(imem_addr), .imem_data(imem_data), .dmem_valid(dmem_valid), .dmem_we(dmem_we),
        .dmem_addr(dmem_addr), .dmem_wdata(dmem_wdata), .dmem_be(dmem_be), .dmem_rdata(dmem_rdata),
        .dmem_ready(dmem_ready), .ret_valid(ret_valid), .ret_pc(ret_pc), .ret_insn(ret_insn), .ret_wdata(ret_wdata),
        .ret_mem_addr(ret_mem_addr), .ret_mem_data(ret_mem_data), .ret_rd(ret_rd), .ret_mem(ret_mem),
        .perf_ctrl(perf_ctrl), .perf_flush(perf_flush),
        .halted({dbg_reg_rdata, dbg_reg_known, dbg_halted, halted}));
    /* verilator lint_off UNUSEDSIGNAL */
    wire perf_unused = &{1'b0, perf_ctrl, perf_flush};
    /* verilator lint_on UNUSEDSIGNAL */
endmodule
