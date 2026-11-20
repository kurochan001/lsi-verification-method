// The core, its debug module and the transport on the JTAG TAP. The core has its own reset, so
// that a debugger can request a halt before the core starts.
module debug_system #(parameter MUTATION = 0, PREDICT = 0, CMD_CYCLES = 512, IDCODE = 32'h12345679) (
    input  wire        clk, rst_n, core_rst_n, irq,
    input  wire        tck, tms, tdi, trst_n,
    output wire        tdo,
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
    output wire        halted, dbg_halted);
    wire dmi_req, haltreq, resumereq, reg_we, reg_known;
    wire [1:0] dmi_op;
    wire [6:0] dmi_addr;
    wire [31:0] dmi_wdata, dmi_rdata, reg_wdata, reg_rdata;
    wire [15:0] regno;
    debug_dtm #(.IDCODE(IDCODE)) dtm(.tck(tck), .tms(tms), .tdi(tdi), .trst_n(trst_n), .tdo(tdo), .dmi_req(dmi_req),
        .dmi_op(dmi_op), .dmi_addr(dmi_addr), .dmi_wdata(dmi_wdata), .dmi_rdata(dmi_rdata));
    debug_module #(.MUTATION(MUTATION), .CMD_CYCLES(CMD_CYCLES)) dm(.clk(clk), .rst_n(rst_n), .dmi_req(dmi_req),
        .dmi_op(dmi_op), .dmi_addr(dmi_addr), .dmi_wdata(dmi_wdata), .dmi_rdata(dmi_rdata), .haltreq(haltreq),
        .resumereq(resumereq), .reg_we(reg_we), .regno(regno), .reg_wdata(reg_wdata), .halted(dbg_halted),
        .reg_known(reg_known), .reg_rdata(reg_rdata));
    rv32i_debug_core #(.MUTATION(MUTATION), .PREDICT(PREDICT)) cpu(.clk(clk), .rst_n(core_rst_n), .irq(irq),
        .imem_addr(imem_addr), .imem_data(imem_data), .dmem_valid(dmem_valid), .dmem_we(dmem_we), .dmem_addr(dmem_addr),
        .dmem_wdata(dmem_wdata), .dmem_be(dmem_be), .dmem_rdata(dmem_rdata), .dmem_ready(dmem_ready),
        .ret_valid(ret_valid), .ret_pc(ret_pc), .ret_insn(ret_insn), .ret_wdata(ret_wdata), .ret_mem_addr(ret_mem_addr),
        .ret_mem_data(ret_mem_data), .ret_rd(ret_rd), .ret_mem(ret_mem), .halted(halted), .dbg_haltreq(haltreq),
        .dbg_resumereq(resumereq), .dbg_reg_we(reg_we), .dbg_regno(regno), .dbg_reg_wdata(reg_wdata),
        .dbg_halted(dbg_halted), .dbg_reg_known(reg_known), .dbg_reg_rdata(reg_rdata));
endmodule
