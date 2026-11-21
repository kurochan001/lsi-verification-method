// Secure boot teaching SoC: the RV32I core of local-riscv-iss (with machine-mode traps), a
// small RAM, the boot verification block and the register block of local-secure-lifecycle.
// The boot ROM and the boot flash are outside (the bench holds them); the one-time
// programmable values (digest, minimum version, key, lifecycle) arrive on ports.
//
// Memory map. Fetch: 0x0000-0x0fff boot ROM, 0x1000-0x13ff boot flash (header at 0x1000,
// image entry at 0x1004); any other fetch returns EBREAK. Data: 0x2000-0x23ff RAM,
// 0x40000000 boot block (CTRL 0x00, STATUS 0x04, IRQ 0x08, INFO 0x0c, KEY0..3 0x10-0x1c),
// 0x40000100 lifecycle block. Other data addresses and writes to read-only registers are bus
// errors: a load returns 0, a store changes nothing, and bus_error pulses.
//
// What the verdict unlocks is decided here in hardware, not by the ROM:
//   - an instruction fetch from the flash returns the flash word only after PASS and only
//     inside the verified payload [0x1004, 0x1004 + length); otherwise it returns EBREAK;
//   - KEY0..3 read the OTP key only after PASS, and 0 before;
//   - the lifecycle block sees the bus as secure only after PASS;
//   - debug_enable is PASS and a lifecycle that allows debug (TEST or DEV).
// Mutations 4 (key gate opens on FAIL), 5 (fetch gate open until FAIL), 6 (no upper bound of
// the fetch gate) and 8 (debug ignores the lifecycle) belong here; 1-3, 7 and 9 to boot_ctrl.
module secure_boot_soc #(parameter IMG_MAX = 112, WAIT = 0, MUTATION = 0) (
    input  wire         clk, rst_n,
    output wire [31:0]  fetch_addr,       // to the bench's ROM and flash
    input  wire [31:0]  fetch_data,
    output wire [7:0]   flash_addr,       // read port of the boot block into the flash
    input  wire [31:0]  flash_data,
    input  wire [255:0] otp_digest,
    input  wire [7:0]   otp_min_version,
    input  wire [127:0] otp_key,
    input  wire [1:0]   lifecycle,        // 0 TEST, 1 DEV, 2 PROD, 3 RMA
    input  wire         irq_req,          // external interrupt source (a pulse)
    output wire         debug_enable,
    output wire [7:0]   boot_status,      // STATUS[7:0]: reason, 0, fail, pass, busy
    output reg          bus_error,        // one clock per refused access
    output wire         ret_valid,
    output wire [31:0]  ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data,
    output wire [4:0]   ret_rd,
    output wire [1:0]   ret_mem,
    output wire         halted
);
    localparam [31:0] EBREAK = 32'h00100073, ENTRY = 32'h00001004;
    wire [31:0] imem_addr, dmem_addr, dmem_wdata, dmem_rdata;
    wire dmem_valid, dmem_we, dmem_ready;
    wire [3:0] dmem_be;
    reg irq_pending;
    wire [31:0] perf_ctrl, perf_flush;

    // Asynchronous assertion, synchronous release: the boot block, the bus and the lifecycle
    // registers clear the moment rst_n falls; the core and the hash engine, which reset on a
    // clock edge, leave reset two clocks after rst_n rises.
    reg [1:0] release_q;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) release_q <= 2'b00;
        else release_q <= {release_q[0], 1'b1};
    end
    wire sync_rst_n = release_q[1];

    // ---- boot verification and the hardware gates ----
    wire busy, pass, fail;
    wire [3:0] reason;
    wire [7:0] plen, version;
    wire boot_sel = dmem_addr[31:8] == 24'h400000;
    wire lc_sel = dmem_addr[31:8] == 24'h400001;
    wire ram_sel = dmem_addr[31:10] == 22'h8;
    wire [7:0] off = dmem_addr[7:0];
    wire access = dmem_valid && dmem_ready;
    wire boot_write = access && dmem_we && boot_sel;
    boot_ctrl #(.IMG_MAX(IMG_MAX), .MUTATION(MUTATION)) boot (
        .clk(clk), .rst_n(rst_n), .engine_rst_n(sync_rst_n), .start(boot_write && off == 8'h00 && dmem_wdata[0]),
        .status_write(boot_write && off == 8'h04), .status_wdata(dmem_wdata),
        .flash_addr(flash_addr), .flash_data(flash_data), .otp_digest(otp_digest),
        .otp_min_version(otp_min_version), .busy(busy), .pass(pass), .fail(fail), .reason(reason),
        .plen(plen), .version(version));
    assign boot_status = {reason, 1'b0, fail, pass, busy};

    wire key_open = MUTATION == 4 ? pass || fail : pass;
    wire exec_open = MUTATION == 5 ? !fail : pass;
    wire [31:0] verified_end = ENTRY + {24'd0, plen};
    wire in_rom = imem_addr < 32'h00001000;
    wire in_flash = imem_addr >= 32'h00001000 && imem_addr < 32'h00001400;
    wire fetch_ok = exec_open && imem_addr[1:0] == 2'b00 && imem_addr >= ENTRY &&
                    (MUTATION == 6 || imem_addr < verified_end);
    assign fetch_addr = imem_addr;
    wire [31:0] imem_data = in_rom || (in_flash && fetch_ok) ? fetch_data : EBREAK;
    assign debug_enable = pass && (MUTATION == 8 || lifecycle == 2'd0 || lifecycle == 2'd1);

    rv32i_core #(.TRAPS(1)) cpu (
        .clk(clk), .rst_n(sync_rst_n), .irq(irq_pending), .imem_addr(imem_addr), .imem_data(imem_data),
        .dmem_valid(dmem_valid), .dmem_we(dmem_we), .dmem_addr(dmem_addr), .dmem_wdata(dmem_wdata),
        .dmem_be(dmem_be), .dmem_rdata(dmem_rdata), .dmem_ready(dmem_ready), .ret_valid(ret_valid),
        .ret_pc(ret_pc), .ret_insn(ret_insn), .ret_wdata(ret_wdata), .ret_mem_addr(ret_mem_addr),
        .ret_mem_data(ret_mem_data), .ret_rd(ret_rd), .ret_mem(ret_mem), .perf_ctrl(perf_ctrl),
        .perf_flush(perf_flush), .halted(halted));

    // ---- data bus: WAIT clocks before each access ----
    reg [3:0] waited;
    assign dmem_ready = WAIT == 0 || waited == WAIT[3:0];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) waited <= 0;
        else if (dmem_valid && !dmem_ready) waited <= waited + 4'd1;
        else waited <= 0;
    end

    // ---- RAM ----
    reg [31:0] ram [0:255];
    always @(posedge clk) begin
        if (access && dmem_we && ram_sel) begin
            if (dmem_be[0]) ram[dmem_addr[9:2]][7:0] <= dmem_wdata[7:0];
            if (dmem_be[1]) ram[dmem_addr[9:2]][15:8] <= dmem_wdata[15:8];
            if (dmem_be[2]) ram[dmem_addr[9:2]][23:16] <= dmem_wdata[23:16];
            if (dmem_be[3]) ram[dmem_addr[9:2]][31:24] <= dmem_wdata[31:24];
        end
    end

    // ---- lifecycle registers: secure only after PASS ----
    wire [31:0] lc_rdata;
    wire lc_error, lc_irq;
    secure_lifecycle lc (
        .clk(clk), .rst_n(rst_n), .cs(dmem_valid && dmem_ready && lc_sel), .we(dmem_we), .re(!dmem_we),
        .addr(off), .wdata(dmem_wdata), .secure(pass), .lifecycle(lifecycle), .debug_key(16'h0000),
        .tamper(1'b0), .rdata(lc_rdata), .error(lc_error), .irq(lc_irq));

    // ---- boot block registers ----
    reg [31:0] boot_rdata;
    reg boot_error;
    always @* begin
        boot_rdata = 32'd0; boot_error = 1'b0;
        case (off)
            8'h00: boot_error = 1'b0;                       // CTRL: writes start, reads 0
            8'h04: begin boot_rdata = {24'd0, boot_status}; boot_error = dmem_we; end
            8'h08: boot_rdata = {31'd0, irq_pending};         // IRQ: a write of 1 acknowledges
            8'h0c: begin boot_rdata = {16'd0, version, plen}; boot_error = dmem_we; end
            8'h10: begin boot_rdata = key_open ? otp_key[127:96] : 32'd0; boot_error = dmem_we; end
            8'h14: begin boot_rdata = key_open ? otp_key[95:64] : 32'd0; boot_error = dmem_we; end
            8'h18: begin boot_rdata = key_open ? otp_key[63:32] : 32'd0; boot_error = dmem_we; end
            8'h1c: begin boot_rdata = key_open ? otp_key[31:0] : 32'd0; boot_error = dmem_we; end
            default: boot_error = 1'b1;
        endcase
    end
    assign dmem_rdata = ram_sel ? ram[dmem_addr[9:2]] : boot_sel ? boot_rdata : lc_sel ? lc_rdata : 32'd0;
    wire refused = boot_sel ? boot_error : lc_sel ? lc_error : !ram_sel;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin irq_pending <= 0; bus_error <= 0; end
        else begin
            bus_error <= access && refused;
            if (irq_req) irq_pending <= 1;
            else if (boot_write && off == 8'h08 && dmem_wdata[0]) irq_pending <= 0;
        end
    end
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused = &{1'b0, perf_ctrl, perf_flush, lc_irq, dmem_addr[1:0], busy};
    /* verilator lint_on UNUSEDSIGNAL */
endmodule
