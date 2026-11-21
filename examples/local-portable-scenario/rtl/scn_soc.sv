// SoC of the portable scenario example: the RV32I core of local-riscv-iss (without traps), a
// 256-word RAM shared by the core and the DMA, and the DMA of this example.
//
// Memory map. Fetch: the bench's ROM. Data: 0x2000-0x23ff RAM, 0x40000000-0x400000ff DMA
// registers; other addresses read 0 and ignore writes. Every data access waits WAIT clocks.
// The RAM has one port. The core has priority: while a core access to the RAM is pending, the
// DMA's memory request waits. The bench reads the RAM through dbg_addr and dbg_data.
//
// Mutations here (5 and 6) are integration errors that the block-level bench cannot see:
// 5 lets the DMA through while the core holds the RAM port, so the DMA's write is lost and its
// read returns the word the core addresses; 6 decodes the DMA window without address bit 4, so
// the core's accesses to channel 1 land on channel 0. Mutations 1 to 4 belong to scn_dma.
module scn_soc #(parameter WAIT = 0, MUTATION = 0) (
    input  wire        clk, rst_n,
    output wire [31:0] fetch_addr,
    input  wire [31:0] fetch_data,
    input  wire [7:0]  dbg_addr,
    output wire [31:0] dbg_data,
    output wire        ret_valid,
    output wire [31:0] ret_pc, ret_insn, ret_mem_addr, ret_mem_data,
    output wire [1:0]  ret_mem,
    output wire        halted,
    output wire [1:0]  dma_irq, dma_busy,
    output wire        dma_stall
);
    wire [31:0] dmem_addr, dmem_wdata, dmem_rdata, ret_wdata;
    wire [4:0] ret_rd;
    wire dmem_valid, dmem_we, dmem_ready;
    wire [3:0] dmem_be;
    wire [31:0] perf_ctrl, perf_flush;

    rv32i_core cpu (
        .clk(clk), .rst_n(rst_n), .irq(1'b0), .imem_addr(fetch_addr), .imem_data(fetch_data),
        .dmem_valid(dmem_valid), .dmem_we(dmem_we), .dmem_addr(dmem_addr), .dmem_wdata(dmem_wdata),
        .dmem_be(dmem_be), .dmem_rdata(dmem_rdata), .dmem_ready(dmem_ready), .ret_valid(ret_valid),
        .ret_pc(ret_pc), .ret_insn(ret_insn), .ret_wdata(ret_wdata), .ret_mem_addr(ret_mem_addr),
        .ret_mem_data(ret_mem_data), .ret_rd(ret_rd), .ret_mem(ret_mem), .perf_ctrl(perf_ctrl),
        .perf_flush(perf_flush), .halted(halted));

    // ---- core data bus: WAIT clocks before each access ----
    reg [3:0] waited;
    assign dmem_ready = WAIT == 0 || waited == WAIT[3:0];
    always @(posedge clk) begin
        if (!rst_n || !(dmem_valid && !dmem_ready)) waited <= 0;
        else waited <= waited + 4'd1;
    end
    wire ram_sel = dmem_addr[31:10] == 22'h8;
    wire dma_sel = dmem_addr[31:8] == 24'h400000;
    wire core_ram = dmem_valid && ram_sel;           // the core holds the RAM port

    // ---- DMA ----
    wire d_valid, d_we;
    wire [7:0] d_addr;
    wire [31:0] d_wdata, d_rdata, reg_rdata;
    wire d_ready = MUTATION == 5 ? 1'b1 : !core_ram;
    assign dma_stall = d_valid && core_ram;
    scn_dma #(.MUTATION(MUTATION)) dma (
        .clk(clk), .rst_n(rst_n), .reg_valid(dmem_valid && dmem_ready && dma_sel), .reg_we(dmem_we),
        .reg_addr(MUTATION == 6 ? dmem_addr[7:0] & 8'hEF : dmem_addr[7:0]), .reg_wdata(dmem_wdata),
        .reg_rdata(reg_rdata), .mem_valid(d_valid), .mem_we(d_we), .mem_addr(d_addr), .mem_wdata(d_wdata),
        .mem_rdata(d_rdata), .mem_ready(d_ready), .irq(dma_irq), .busy_out(dma_busy));

    // ---- RAM: one port, the core first ----
    reg [31:0] ram [0:255];
    wire [7:0] port_addr = core_ram ? dmem_addr[9:2] : d_addr;
    assign d_rdata = ram[port_addr];
    assign dmem_rdata = ram_sel ? ram[dmem_addr[9:2]] : dma_sel ? reg_rdata : 32'd0;
    assign dbg_data = ram[dbg_addr];
    always @(posedge clk) begin
        if (core_ram && dmem_ready && dmem_we) begin
            if (dmem_be[0]) ram[dmem_addr[9:2]][7:0] <= dmem_wdata[7:0];
            if (dmem_be[1]) ram[dmem_addr[9:2]][15:8] <= dmem_wdata[15:8];
            if (dmem_be[2]) ram[dmem_addr[9:2]][23:16] <= dmem_wdata[23:16];
            if (dmem_be[3]) ram[dmem_addr[9:2]][31:24] <= dmem_wdata[31:24];
        end else if (!core_ram && d_valid && d_we && d_ready) ram[d_addr] <= d_wdata;
    end
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused = &{1'b0, perf_ctrl, perf_flush, ret_wdata, ret_rd, dmem_addr[1:0]};
    /* verilator lint_on UNUSEDSIGNAL */
endmodule
