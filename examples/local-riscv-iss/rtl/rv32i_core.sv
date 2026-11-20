// Five-stage RV32I pipeline: aligned loads and stores of bytes, halfwords and words, EBREAK
// halts. TRAPS adds machine-mode CSRs, exceptions, an external interrupt and MRET (see MEM).
// Results are forwarded from EX/MEM and MEM/WB, the register file passes a value written in
// the same cycle, a load followed by its use costs one bubble, and branches and jumps are
// resolved in EX, flushing the two younger instructions. While data memory waits, every
// stage holds and WB receives a bubble. The retirement port shows each instruction that
// leaves WB, for comparison with an instruction set simulator. PREDICT adds branch
// prediction in IF (see below); the default 0 fetches sequentially. PRIV (with TRAPS) adds user
// mode, mstatus.MPP/MPRV/TW, timer and software interrupts, vectored mtvec, WFI and physical
// memory protection with the checker of local-riscv-pmp; mutations 18 to 23 belong to it.
// DEBUG adds a debug mode for an external debug module (local-riscv-debug): halt request,
// resume, single step, dcsr and dpc, EBREAK into debug mode and access to the registers while
// halted; mutations 24 to 27 belong to it. The port list stays the same for every example that
// instantiates the core: with DEBUG the requests travel above the interrupt lines of irq and
// the answers above bit 0 of halted. rv32i_debug_core of local-riscv-debug gives them names.
module rv32i_core #(parameter MUTATION = 0, PREDICT = 0, TRAPS = 0, PRIV = 0, DEBUG = 0) (
    input  wire        clk, rst_n,
    // Bit 0: machine external interrupt line (TRAPS). With PRIV the port is three bits wide:
    // bit 1 is the timer line and bit 2 the software line. With DEBUG, 51 more bits follow the
    // lines: halt request (a level), resume request (a pulse), register write enable, register
    // number (0x1000 + n for xn, 0x7b0 dcsr, 0x7b1 dpc) and write data.
    input  wire [(PRIV != 0 ? 2 : 0) + (DEBUG != 0 ? 51 : 0):0] irq,
    output wire [31:0] imem_addr,
    input  wire [31:0] imem_data,
    output wire        dmem_valid, dmem_we,
    output wire [31:0] dmem_addr, dmem_wdata,
    output wire [3:0]  dmem_be,                 // byte enables of a store
    input  wire [31:0] dmem_rdata,
    input  wire        dmem_ready,
    output wire        ret_valid,
    output wire [31:0] ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data,
    output wire [4:0]  ret_rd,
    output wire [1:0]  ret_mem,
    output reg  [31:0] perf_ctrl, perf_flush,  // resolved branches and jumps; redirects from EX
    // Bit 0: stopped by the EBREAK that ends the program. With DEBUG, 34 more bits: in debug
    // mode, the register number is one this core has, and the value read from that register.
    output wire [(DEBUG != 0 ? 34 : 0):0] halted);
    localparam [6:0] LUI = 7'h37, AUIPC = 7'h17, JAL = 7'h6f, JALR = 7'h67, BRANCH = 7'h63,
                     LOAD = 7'h03, STORE = 7'h23, OPIMM = 7'h13, OP = 7'h33;
    localparam [6:0] SYSTEM = 7'h73;
    localparam [31:0] EBREAK = 32'h00100073, ECALL = 32'h00000073, MRET = 32'h30200073, WFI = 32'h10500073;

    reg [31:0] pc;
    reg stopped;
    reg [31:0] regs [1:31];
    reg id_valid, ex_valid, ex_wen, mem_valid, mem_wen, wb_valid, wb_wen;
    reg [31:0] id_pc, id_insn, ex_pc, ex_insn, ex_imm, ex_a, ex_b;
    reg [31:0] mem_pc, mem_insn, mem_result, mem_store, wb_pc, wb_insn, wb_data, wb_addr, wb_mdata, wb_raw;
    reg wb_load;
    reg [4:0] ex_rd, mem_rd, wb_rd;
    reg [1:0] wb_mem;
    reg id_pred, ex_pred;
    reg [3:0] ex_code, mem_code;      // exception cause of the instruction, 0 for none
    reg ex_csr, ex_mret, mem_csr, mem_mret, wb_trap;
    reg [31:0] mem_tval, mem_csr_src;
    // machine-mode CSRs (only the fields this core implements)
    reg st_mie, st_mpie, ie_meie;
    reg [29:0] tvec, epc;
    reg [31:0] scratch, cause, tval;
    // PRIV: the current privilege (1 machine, 0 user) and the added CSR fields. Without PRIV they
    // keep their reset values: machine mode, MPP = M, everything else 0.
    reg priv_m, st_mpp_m, st_mprv, st_tw, ie_msie, ie_mtie, tvec_mode;
    reg id_fault, ex_wfi, mem_wfi, wfi_waited;
    reg [1:0] pmp_idx;
    reg [31:0] pmp_old;
    // DEBUG: debug mode, dcsr.ebreakm, dcsr.step, dcsr.cause, dpc, and the state of a single step.
    reg dbg_mode, dc_ebreakm, dc_step, step_armed, step_pending, step_seen;
    reg [2:0] dc_cause;
    reg [29:0] dpc;
    wire dbg_enter;
    wire [2:0] lines;  // software, timer, external
    generate if (PRIV != 0) begin : g_lines
        assign lines = irq[2:0];
    end else begin : g_line
        assign lines = {2'b00, irq[0]};
    end endgenerate
    localparam LW = PRIV != 0 ? 3 : 1;  // interrupt lines in irq
    wire dbg_haltreq, dbg_resumereq, dbg_reg_we, dbg_halted, dbg_reg_known;
    wire [15:0] dbg_regno;
    wire [31:0] dbg_reg_wdata, dbg_reg_rdata;
    generate if (DEBUG != 0) begin : g_debug
        assign {dbg_reg_wdata, dbg_regno, dbg_reg_we, dbg_resumereq, dbg_haltreq} = irq[LW + 50:LW];
        assign halted = {dbg_reg_rdata, dbg_reg_known, dbg_halted, stopped};
    end else begin : g_no_debug
        assign {dbg_reg_wdata, dbg_regno, dbg_reg_we, dbg_resumereq, dbg_haltreq} = 51'd0;
        assign halted = stopped;
        /* verilator lint_off UNUSEDSIGNAL */
        wire dbg_unused = &{1'b0, dbg_reg_rdata, dbg_reg_known, dbg_halted};
        /* verilator lint_on UNUSEDSIGNAL */
    end endgenerate
    wire if_allow, mem_allow;      // PMP verdicts for the fetch and for the data access in MEM
    wire [31:0] pmp_configs;       // pmpcfg0
    wire [55:0] pmp_addresses;     // pmpaddr0 to pmpaddr3, 14 bits each
    integer i;
    assign imem_addr = pc;
    // A fetch that PMP denies, or from beyond the 64 KiB of physical memory, becomes an
    // instruction access fault; its word is replaced by zero and never predicted.
    wire if_fault = PRIV != 0 && (!if_allow || pc[31:16] != 16'd0);

    // IF: prediction. PREDICT 1 predicts JAL and backward branches taken; PREDICT 2 predicts JAL
    // taken and branches from 16 two-bit counters indexed by pc[5:2]. Targets come from the
    // fetched word itself; JALR and EBREAK are never predicted.
    wire [6:0] if_op = imem_data[6:0];
    wire [31:0] if_bimm = {{20{imem_data[31]}}, imem_data[7], imem_data[30:25], imem_data[11:8], 1'b0};
    wire [31:0] if_jimm = {{12{imem_data[31]}}, imem_data[19:12], imem_data[20], imem_data[30:21], 1'b0};
    reg [1:0] bht [0:15];
    // Mutation 7 predicts forward branches taken and backward ones not taken.
    wire if_backward = MUTATION == 7 ? !imem_data[31] : imem_data[31];
    wire if_predict = PREDICT != 0 && !if_fault && (if_op == JAL || (if_op == BRANCH && (PREDICT == 1 ? if_backward : bht[pc[5:2]][1])));
    wire [31:0] if_target = pc + (if_op == JAL ? if_jimm : if_bimm);

    // ID: decode and read registers.
    wire [6:0] id_op = id_insn[6:0];
    wire [4:0] id_rs1 = id_insn[19:15], id_rs2 = id_insn[24:20];
    // Legality comes from the decoder proved for all instruction words (local-riscv-decoder);
    // CSR instructions on the implemented CSRs and MRET are added when TRAPS is set.
    wire dec_legal;
    wire [5:0] dec_op;
    wire [31:0] dec_imm;
    wire dec_rd_we, dec_rs1_used, dec_rs2_used;
    rv32i_decoder dec(.insn(id_insn), .legal(dec_legal), .op(dec_op), .imm(dec_imm), .rd_we(dec_rd_we),
                      .rs1_used(dec_rs1_used), .rs2_used(dec_rs2_used));
    /* verilator lint_off UNUSEDSIGNAL */
    wire dec_unused = &{1'b0, dec_op, dec_imm, dec_rd_we, dec_rs1_used, dec_rs2_used};
    /* verilator lint_on UNUSEDSIGNAL */
    wire [11:0] id_csr_addr = id_insn[31:20];
    wire id_csr_known = id_csr_addr == 12'h300 || id_csr_addr == 12'h304 || id_csr_addr == 12'h305 ||
                        id_csr_addr == 12'h340 || id_csr_addr == 12'h341 || id_csr_addr == 12'h342 ||
                        id_csr_addr == 12'h343 || id_csr_addr == 12'h344;
    wire id_pmp_csr = PRIV != 0 && (id_csr_addr == 12'h3a0 || id_csr_addr[11:2] == 10'h0ec);  // pmpcfg0, pmpaddr0..3
    // Every implemented CSR and MRET are machine-level: in user mode they are illegal instructions
    // (mutation 23 lets user mode use them). WFI is illegal in user mode when mstatus.TW is set.
    // The privilege seen here is the one the instruction executes in: traps and MRET, the only
    // things that change it, discard everything younger.
    wire id_machine = priv_m || MUTATION == 23;
    wire id_csr = TRAPS != 0 && id_op == SYSTEM && id_insn[13:12] != 2'd0 && (id_csr_known || id_pmp_csr) && id_machine;
    wire id_mret = TRAPS != 0 && id_insn == MRET && id_machine;
    wire id_wfi = PRIV != 0 && id_insn == WFI && (priv_m || !st_tw);
    wire [3:0] id_code = TRAPS == 0 ? 4'd0 : id_fault ? 4'd1 : !(dec_legal || id_csr || id_mret || id_wfi) ? 4'd2 :
                         id_insn == ECALL ? (priv_m ? 4'd11 : 4'd8) : 4'd0;
    wire id_use1 = id_op == JALR || id_op == BRANCH || id_op == LOAD || id_op == STORE || id_op == OPIMM || id_op == OP ||
                   (id_csr && !id_insn[14]);
    wire id_use2 = id_op == BRANCH || id_op == STORE || id_op == OP;
    wire id_wen = (id_op == LUI || id_op == AUIPC || id_op == JAL || id_op == JALR || id_op == LOAD ||
                   id_op == OPIMM || id_op == OP || id_csr) && id_code == 4'd0;
    reg [31:0] id_imm;
    always @* case (id_op)
        LUI, AUIPC: id_imm = {id_insn[31:12], 12'd0};
        JAL:        id_imm = {{12{id_insn[31]}}, id_insn[19:12], id_insn[20], id_insn[30:21], 1'b0};
        BRANCH:     id_imm = {{20{id_insn[31]}}, id_insn[7], id_insn[30:25], id_insn[11:8], 1'b0};
        STORE:      id_imm = {{21{id_insn[31]}}, id_insn[30:25], id_insn[11:7]};
        default:    id_imm = {{21{id_insn[31]}}, id_insn[30:20]};
    endcase
    wire wb_write = wb_valid && wb_wen && wb_rd != 0 && !stopped;
    wire [31:0] rf1 = id_rs1 == 0 ? 32'd0 : wb_write && wb_rd == id_rs1 ? wb_data : regs[id_rs1];
    wire [31:0] rf2 = id_rs2 == 0 ? 32'd0 : wb_write && wb_rd == id_rs2 ? wb_data : regs[id_rs2];
    // A load in EX cannot forward to the next instruction: hold it in ID for one cycle.
    // Mutation 2 omits the bubble.
    // A CSR instruction reads its CSR in MEM, so its result also waits a cycle (mutation 16 forgets).
    wire load_use = MUTATION != 2 && id_valid && ex_valid && (ex_insn[6:0] == LOAD || (ex_csr && MUTATION != 16)) &&
                    ex_rd != 0 && ((id_use1 && id_rs1 == ex_rd) || (id_use2 && id_rs2 == ex_rd));

    // EX: forward, compute, resolve branches. The younger producer (EX/MEM) wins.
    // Mutation 1 also forwards results addressed to x0.
    wire [6:0] ex_op = ex_insn[6:0];
    wire [2:0] ex_f3 = ex_insn[14:12];
    wire [4:0] ex_rs1 = ex_insn[19:15], ex_rs2 = ex_insn[24:20];
    wire mem_fwd_ok = mem_valid && mem_wen && (mem_rd != 0 || MUTATION == 1);
    wire wb_fwd_ok = wb_valid && wb_wen && (wb_rd != 0 || MUTATION == 1);
    // Mutation 12 forwards the raw memory word of a load from WB instead of its extended value.
    wire [31:0] wb_fwd = MUTATION == 12 && wb_load ? wb_raw : wb_data;
    wire [31:0] a = mem_fwd_ok && mem_rd == ex_rs1 ? mem_result : wb_fwd_ok && wb_rd == ex_rs1 ? wb_fwd : ex_a;
    wire [31:0] b = mem_fwd_ok && mem_rd == ex_rs2 ? mem_result : wb_fwd_ok && wb_rd == ex_rs2 ? wb_fwd : ex_b;
    wire [31:0] src2 = ex_op == OP ? b : ex_imm;
    wire alt = ex_insn[30] && (ex_op == OP || (ex_op == OPIMM && ex_f3 == 3'd5));
    reg [31:0] alu;
    always @* case (ex_f3)
        3'd0: alu = alt ? a - src2 : a + src2;
        3'd1: alu = a << src2[4:0];
        3'd2: alu = {31'd0, $signed(a) < $signed(src2)};
        3'd3: alu = {31'd0, a < src2};
        3'd4: alu = a ^ src2;
        3'd5: alu = alt ? $unsigned($signed(a) >>> src2[4:0]) : a >> src2[4:0];
        3'd6: alu = a | src2;
        default: alu = a & src2;
    endcase
    reg cond;
    always @* case (ex_f3)
        3'd0: cond = a == b;
        3'd1: cond = a != b;
        3'd4: cond = $signed(a) < $signed(b);
        3'd5: cond = $signed(a) >= $signed(b);
        3'd6: cond = a < b;
        3'd7: cond = a >= b;
        default: cond = 1'b0;
    endcase
    // Mutation 3 computes the JALR target from the register value read in ID, unforwarded.
    wire [31:0] jalr_base = MUTATION == 3 ? ex_a : a;
    wire ex_ebreak = ex_insn == EBREAK;  // jumps to itself; the first one to retire halts
    wire taken = ex_valid && ex_code == 4'd0 && (ex_op == JAL || ex_op == JALR || (ex_op == BRANCH && cond) || ex_ebreak);
    wire [31:0] target = ex_op == JALR ? (jalr_base + ex_imm) & ~32'd1 : ex_ebreak ? ex_pc : ex_pc + ex_imm;
    // A wrong prediction (taken or not) redirects fetch and flushes the two younger instructions.
    // A right one costs nothing: the predicted target is the same pc + immediate. Mutation 6 also
    // flushes after a right taken prediction; mutation 5 resumes a predicted-taken branch that
    // falls through at its target.
    wire redirect = ex_valid && (taken != ex_pred || (MUTATION == 6 && ex_pred));
    wire [31:0] resume = taken || (MUTATION == 5 && ex_pred) ? target : ex_pc + 32'd4;
    wire [1:0] counter = bht[ex_pc[5:2]];
    wire [31:0] ex_result = ex_op == LUI ? ex_imm : ex_op == AUIPC ? ex_pc + ex_imm :
                            ex_op == JAL || ex_op == JALR ? ex_pc + 32'd4 :
                            ex_op == LOAD || ex_op == STORE ? a + ex_imm : alu;
    // Misaligned accesses become exceptions (TRAPS); the address is the trap value.
    wire ex_misaligned = TRAPS != 0 && (ex_op == LOAD || ex_op == STORE) &&
                         (ex_f3[1:0] == 2'd1 ? ex_result[0] : ex_f3[1:0] == 2'd2 ? ex_result[1:0] != 2'd0 : 1'b0);
    wire [3:0] ex_cause = ex_code != 4'd0 ? ex_code : ex_misaligned ? (ex_op == LOAD ? 4'd4 : 4'd6) : 4'd0;
    wire [31:0] ex_tval = ex_code == 4'd1 ? ex_pc : ex_code == 4'd2 ? ex_insn : ex_misaligned ? ex_result : 32'd0;

    // MEM: one word access; the pipeline freezes until the memory is ready.
    wire mem_load = mem_insn[6:0] == LOAD, mem_st = mem_insn[6:0] == STORE;
    // Traps, MRET and CSR writes all take effect in MEM, where every older instruction has
    // finished and no younger one has changed memory or a CSR, so exceptions are precise. An
    // interrupt is taken before the first instruction to reach MEM once it is pending and
    // enabled; mutation 14 ignores mstatus.MIE. A data access that the memory has already seen
    // cannot be withdrawn: a bus may have started it, and its answer would otherwise reach the
    // next access. The interrupt then waits for that access to finish; mutation 17 does not wait.
    // PRIV: machine interrupts are always enabled in user mode. With several pending and enabled,
    // external goes before software, software before timer (mutation 21 reverses the order). An
    // interrupt also waits for a pmpcfg0 write in progress, and a WFI that has waited retires
    // before the interrupt that woke it is taken.
    reg dmem_pending;
    wire pend_e = lines[0] && ie_meie, pend_s = lines[2] && ie_msie, pend_t = lines[1] && ie_mtie;
    // DEBUG: no interrupt is taken during a single step (dcsr.stepie is 0).
    wire irq_take = TRAPS != 0 && mem_valid && (pend_e || pend_s || pend_t) && (st_mie || !priv_m || MUTATION == 14) &&
                    (!dmem_pending || MUTATION == 17) && pmp_idx == 2'd0 && !step_armed && !(mem_wfi && wfi_waited);
    wire [3:0] irq_code = MUTATION == 21 ? (pend_t ? 4'd7 : pend_s ? 4'd3 : 4'd11) : pend_e ? 4'd11 : pend_s ? 4'd3 : 4'd7;
    // PRIV: a load or store is checked with the effective privilege (MPP when MPRV is set;
    // mutation 19 ignores MPRV; see g_pmp). A denied or out-of-range access is an access fault; a
    // misaligned address, found in EX, goes first.
    wire mem_access = mem_insn[6:0] == LOAD || mem_insn[6:0] == STORE;
    wire mem_fault = PRIV != 0 && mem_valid && mem_access && mem_code == 4'd0 && (!mem_allow || mem_result[31:16] != 16'd0);
    wire [3:0] mem_cause = mem_code != 4'd0 ? mem_code : !mem_fault ? 4'd0 : mem_insn[6:0] == LOAD ? 4'd5 : 4'd7;
    wire exc_take = TRAPS != 0 && mem_valid && mem_cause != 4'd0;
    wire trap = irq_take || exc_take;
    wire mret_take = mem_valid && mem_mret && !trap;
    wire [31:0] trap_cause = irq_take ? {28'h8000000, irq_code} : {28'd0, mem_cause};
    wire [31:0] trap_tval = irq_take ? 32'd0 : mem_code != 4'd0 ? mem_tval : mem_result;
    // Vectored mtvec sends an interrupt to base + 4 * cause (mutation 22 always uses the base).
    wire [31:0] trap_pc = {tvec, 2'b00} + (tvec_mode && irq_take && MUTATION != 22 ? {26'd0, irq_code, 2'b00} : 32'd0);
    reg [31:0] csr_old;
    always @* case (mem_insn[31:20])
        12'h300: csr_old = {10'd0, st_tw, 3'd0, st_mprv, 4'd0, {2{st_mpp_m}}, 3'd0, st_mpie, 3'd0, st_mie, 3'd0};  // mstatus
        12'h304: csr_old = {20'd0, ie_meie, 3'd0, ie_mtie, 3'd0, ie_msie, 3'd0};  // mie
        12'h305: csr_old = {tvec, 1'b0, tvec_mode};                              // mtvec
        12'h340: csr_old = scratch;
        12'h341: csr_old = {epc, 2'b00};
        12'h342: csr_old = cause;
        12'h343: csr_old = tval;
        12'h3a0: csr_old = pmp_idx == 2'd0 ? pmp_configs : pmp_old;              // pmpcfg0
        12'h3b0: csr_old = {18'd0, pmp_addresses[13:0]};
        12'h3b1: csr_old = {18'd0, pmp_addresses[27:14]};
        12'h3b2: csr_old = {18'd0, pmp_addresses[41:28]};
        12'h3b3: csr_old = {18'd0, pmp_addresses[55:42]};
        default: csr_old = {20'd0, lines[0], 3'd0, lines[1], 3'd0, lines[2], 3'd0};  // mip, read-only here
    endcase
    // CSRRW writes always; CSRRS/CSRRC (and the immediate forms) write only with a nonzero rs1.
    wire csr_we = mem_valid && mem_csr && (mem_insn[13:12] == 2'd1 || mem_insn[19:15] != 5'd0);
    wire [31:0] csr_new = mem_insn[13:12] == 2'd1 ? mem_csr_src : mem_insn[13:12] == 2'd2 ? csr_old | mem_csr_src :
                          csr_old & ~mem_csr_src;
    // PRIV: the PMP checker takes one configuration byte at a time, so a write of pmpcfg0 holds
    // the pipeline for three cycles and writes its four bytes in turn; rd gets the value read in
    // the first cycle. A write of a PMP CSR discards the younger instructions, which were
    // fetched under the old settings, and fetches again.
    wire pmp_cfg_wr = PRIV != 0 && csr_we && !trap && mem_insn[31:20] == 12'h3a0;
    wire pmp_addr_wr = PRIV != 0 && csr_we && !trap && mem_insn[31:22] == 10'h0ec;
    wire pmp_freeze = pmp_cfg_wr && pmp_idx != 2'd3;
    wire pmp_flush = (pmp_cfg_wr && pmp_idx == 2'd3) || pmp_addr_wr;
    // PRIV: WFI waits in MEM until an interrupt is pending and enabled in mie, whatever mstatus.MIE says.
    wire wfi_stall = PRIV != 0 && mem_valid && mem_wfi && !(pend_e || pend_s || pend_t) && !trap;
    // Mutation 20 lets a store that PMP denies reach the memory although it traps.
    assign dmem_valid = mem_valid && (mem_load || mem_st) && !stopped && !dbg_enter &&
                        (!trap || (MUTATION == 20 && mem_fault && mem_st && !irq_take));
    assign dmem_we = mem_st;
    assign dmem_addr = mem_result;
    // A store puts its byte or halfword on every lane it may use and enables the addressed ones;
    // a load takes its byte or halfword from the addressed lane and extends it.
    wire [2:0] mem_f3 = mem_insn[14:12];
    wire [1:0] lane = mem_result[1:0];
    wire [1:0] store_lane = MUTATION == 10 ? 2'd0 : lane;  // mutation 10: always the lowest lane
    assign dmem_wdata = mem_f3[1:0] == 2'd0 ? {4{mem_store[7:0]}} : mem_f3[1:0] == 2'd1 ? {2{mem_store[15:0]}} : mem_store;
    assign dmem_be = mem_f3[1:0] == 2'd0 ? 4'b0001 << store_lane : mem_f3[1:0] == 2'd1 ? 4'b0011 << store_lane : 4'b1111;
    wire [1:0] load_lane = MUTATION == 11 ? {lane[1], 1'b0} : lane;  // mutation 11: ignores bit 0
    reg [7:0] byte_in;
    always @* case (load_lane)
        2'd0: byte_in = dmem_rdata[7:0];
        2'd1: byte_in = dmem_rdata[15:8];
        2'd2: byte_in = dmem_rdata[23:16];
        default: byte_in = dmem_rdata[31:24];
    endcase
    wire [15:0] half_in = lane[1] ? dmem_rdata[31:16] : dmem_rdata[15:0];
    wire extend = MUTATION != 9;  // mutation 9 zero-extends LB and LH
    reg [31:0] loaded;
    always @* case (mem_f3)
        3'd0: loaded = {{24{extend & byte_in[7]}}, byte_in};
        3'd1: loaded = {{16{extend & half_in[15]}}, half_in};
        3'd4: loaded = {24'd0, byte_in};
        3'd5: loaded = {16'd0, half_in};
        default: loaded = dmem_rdata;
    endcase
    wire [31:0] stored = mem_f3[1:0] == 2'd0 ? {24'd0, mem_store[7:0]} :
                         mem_f3[1:0] == 2'd1 ? {16'd0, mem_store[15:0]} : mem_store;
    wire freeze = (dmem_valid && !dmem_ready) || pmp_freeze || wfi_stall;
    generate if (PRIV != 0) begin : g_pmp
        wire [2:0] fetch_matched, data_matched;
        wire [31:0] fetch_configs;
        wire [55:0] fetch_addresses;
        wire data_m = st_mprv && MUTATION != 19 ? st_mpp_m : priv_m;
        wire [1:0] pmp_index = pmp_cfg_wr ? pmp_idx : mem_insn[21:20];
        wire [31:0] pmp_wdata = pmp_cfg_wr ? {24'd0, csr_new[8 * pmp_idx +: 8]} : csr_new;
        // The checker resets asynchronously; it gets the reset from a flop of its own.
        reg pmp_rst_n;
        always @(posedge clk) pmp_rst_n <= rst_n;
        // Two copies of the checker receive the same writes: one judges the fetch, one the data access.
        pmp #(.AW(16)) fetch(.clk(clk), .rst_n(pmp_rst_n), .cfg_we(pmp_cfg_wr), .addr_we(pmp_addr_wr), .index(pmp_index),
                             .wdata(pmp_wdata), .address(pc[15:0]), .size_log2(2'd2), .kind(2'd2), .machine(priv_m),
                             .allow(if_allow), .matched(fetch_matched), .configs(fetch_configs), .addresses(fetch_addresses));
        pmp #(.AW(16)) data(.clk(clk), .rst_n(pmp_rst_n), .cfg_we(pmp_cfg_wr), .addr_we(pmp_addr_wr), .index(pmp_index),
                            .wdata(pmp_wdata), .address(mem_result[15:0]), .size_log2(mem_f3[1:0]), .kind({1'b0, mem_st}),
                            .machine(data_m), .allow(mem_allow), .matched(data_matched), .configs(pmp_configs),
                            .addresses(pmp_addresses));
        /* verilator lint_off UNUSEDSIGNAL */
        wire pmp_unused = &{1'b0, fetch_matched, data_matched, fetch_configs, fetch_addresses};
        /* verilator lint_on UNUSEDSIGNAL */
    end else begin : g_no_pmp
        assign if_allow = 1'b1;
        assign mem_allow = 1'b1;
        assign pmp_configs = 32'd0;
        assign pmp_addresses = 56'd0;
    end endgenerate

    // DEBUG: debug mode is entered in MEM, like a trap: before the first instruction to reach
    // MEM once a halt is requested, a single step has finished, or that instruction is an EBREAK
    // with dcsr.ebreakm set. The instruction and everything younger are discarded without any
    // effect and dpc points at it, so that a resume executes it once. Whatever it would have
    // done (an exception, an interrupt taken before it) happens after the resume. A data access
    // the memory has already seen finishes first. A request goes before a finished step, and
    // the step before an EBREAK that has not executed yet.
    assign dbg_enter = DEBUG != 0 && !dbg_mode && mem_valid && !dmem_pending && pmp_idx == 2'd0 &&
                       (dbg_haltreq || step_pending || (dc_ebreakm && mem_insn == EBREAK && MUTATION != 27));
    assign dbg_halted = dbg_mode;
    wire dbg_gpr = dbg_regno[15:5] == 11'h080;
    assign dbg_reg_known = dbg_gpr || dbg_regno == 16'h07b0 || dbg_regno == 16'h07b1;
    // dcsr: debugver 4, ebreakm (15), cause (8:6), step (2), prv 3 (machine mode).
    assign dbg_reg_rdata = dbg_gpr ? (dbg_regno[4:0] == 5'd0 ? 32'd0 : regs[dbg_regno[4:0]]) :
                           dbg_regno == 16'h07b0 ? {4'd4, 12'd0, dc_ebreakm, 6'd0, dc_cause, 3'd0, dc_step, 2'd3} :
                           dbg_regno == 16'h07b1 ? {dpc, 2'b00} : 32'd0;

    // WB: retire.
    assign ret_valid = wb_valid && !stopped;
    assign ret_pc = wb_pc;
    assign ret_insn = wb_insn;
    assign ret_rd = wb_write ? wb_rd : 5'd0;
    assign ret_wdata = wb_write ? wb_data : 32'd0;
    assign ret_mem = wb_mem;
    assign ret_mem_addr = wb_addr;
    assign ret_mem_data = wb_mdata;

    always @(posedge clk) begin
        if (!rst_n) begin
            pc <= 0; stopped <= 0; wb_trap <= 0; dmem_pending <= 0;
            id_valid <= 0; ex_valid <= 0; mem_valid <= 0; wb_valid <= 0;
            st_mie <= 0; st_mpie <= 0; ie_meie <= 0; tvec <= 0; epc <= 0; scratch <= 0; cause <= 0; tval <= 0;
            priv_m <= 1; st_mpp_m <= 1; st_mprv <= 0; st_tw <= 0; ie_msie <= 0; ie_mtie <= 0; tvec_mode <= 0;
            id_fault <= 0; ex_wfi <= 0; mem_wfi <= 0; wfi_waited <= 0; pmp_idx <= 0; pmp_old <= 0;
            perf_ctrl <= 0; perf_flush <= 0;
            dbg_mode <= 0; dc_ebreakm <= 0; dc_step <= 0; dc_cause <= 0; dpc <= 0;
            step_armed <= 0; step_pending <= 0; step_seen <= 0;
            for (i = 0; i < 16; i = i + 1) bht[i] <= 2'b01;  // weakly not taken
        end else if (DEBUG != 0 && dbg_mode) begin
            // Debug mode: the pipeline is empty. The debug module reads and writes registers and
            // resumes at dpc (mutation 26 resumes one instruction early). With dcsr.step the
            // core comes back after one instruction.
            if (dbg_reg_we && dbg_gpr && dbg_regno[4:0] != 5'd0) regs[dbg_regno[4:0]] <= dbg_reg_wdata;
            if (dbg_reg_we && dbg_regno == 16'h07b0) begin dc_ebreakm <= dbg_reg_wdata[15]; dc_step <= dbg_reg_wdata[2]; end
            if (dbg_reg_we && dbg_regno == 16'h07b1) dpc <= dbg_reg_wdata[31:2];
            if (dbg_resumereq) begin
                dbg_mode <= 0; pc <= {MUTATION == 26 ? dpc - 30'd1 : dpc, 2'b00};
                step_armed <= dc_step; step_pending <= 0; step_seen <= 0;
            end
        end else if (!stopped) begin
            if (wb_write) regs[wb_rd] <= wb_data;
            if (wb_valid && !wb_trap && wb_insn == EBREAK) stopped <= 1;
            dmem_pending <= dmem_valid && !dmem_ready;
            // DEBUG: a step is over when its instruction leaves MEM, by retiring or by trapping
            // (mutation 25 lets two instructions leave).
            if (step_armed && mem_valid && (trap || !freeze) && !dbg_enter) begin
                if (MUTATION == 25 && !step_seen) step_seen <= 1;
                else step_pending <= 1;
            end
            if (dbg_enter) begin
                // The instruction in WB retires in this cycle; nothing follows it. Mutation 24
                // saves the address after the discarded instruction; mutation 27 never sees
                // dcsr.ebreakm (see below).
                wb_valid <= 0; mem_valid <= 0; ex_valid <= 0; id_valid <= 0;
                dbg_mode <= 1; dpc <= MUTATION == 24 ? mem_pc[31:2] + 30'd1 : mem_pc[31:2];
                dc_cause <= dbg_haltreq ? 3'd3 : step_pending ? 3'd4 : 3'd1;
                step_armed <= 0; step_pending <= 0;
            end else if (trap) begin
                // The instruction in MEM leaves as a trap record (kind 3: cause, trap value) and
                // everything younger is discarded. Mutation 15 lets a faulting load still write rd;
                // mutation 13 saves the next pc for an exception.
                wb_valid <= 1; wb_pc <= mem_pc; wb_insn <= mem_insn; wb_rd <= mem_rd; wb_trap <= 1; wb_load <= 0;
                wb_wen <= MUTATION == 15 && exc_take && mem_wen; wb_data <= mem_result;
                wb_mem <= 2'd3; wb_addr <= trap_cause; wb_mdata <= trap_tval;
                mem_valid <= 0; ex_valid <= 0; id_valid <= 0;
                pc <= trap_pc;
                epc <= MUTATION == 13 && !irq_take ? mem_pc[31:2] + 30'd1 : mem_pc[31:2];
                cause <= trap_cause; tval <= trap_tval; st_mpie <= st_mie; st_mie <= 0;
                // PRIV: the trap is taken in machine mode and MPP remembers where it came from
                // (mutation 18 leaves MPP as it was).
                if (PRIV != 0) begin priv_m <= 1; wfi_waited <= 0; if (MUTATION != 18) st_mpp_m <= priv_m; end
            end else if (freeze) begin
                // The instruction in WB retires and its forwarding source is gone next cycle,
                // so EX keeps the forwarded operands. Mutation 4 does not.
                wb_valid <= 0;
                if (MUTATION != 4) begin ex_a <= a; ex_b <= b; end
                if (pmp_freeze) begin
                    if (pmp_idx == 2'd0) pmp_old <= pmp_configs;
                    pmp_idx <= pmp_idx + 2'd1;
                end
                if (wfi_stall) wfi_waited <= 1;
            end else begin
                pmp_idx <= 0; wfi_waited <= 0;
                wb_valid <= mem_valid; wb_pc <= mem_pc; wb_insn <= mem_insn; wb_rd <= mem_rd; wb_wen <= mem_wen;
                wb_data <= mem_load ? loaded : mem_csr ? csr_old : mem_result; wb_trap <= 0;
                wb_mem <= mem_load ? 2'd1 : mem_st ? 2'd2 : 2'd0;
                if (csr_we) case (mem_insn[31:20])
                    12'h300: begin
                        st_mie <= csr_new[3]; st_mpie <= csr_new[7];
                        // MPP holds M or U only: any other value written reads back as U.
                        if (PRIV != 0) begin st_mpp_m <= &csr_new[12:11]; st_mprv <= csr_new[17]; st_tw <= csr_new[21]; end
                    end
                    12'h304: begin
                        ie_meie <= csr_new[11];
                        if (PRIV != 0) begin ie_mtie <= csr_new[7]; ie_msie <= csr_new[3]; end
                    end
                    12'h305: begin tvec <= csr_new[31:2]; if (PRIV != 0) tvec_mode <= csr_new[0]; end
                    12'h340: scratch <= csr_new;
                    12'h341: epc <= csr_new[31:2];
                    12'h342: cause <= csr_new;
                    12'h343: tval <= csr_new;
                    default: ;  // mip: writes are ignored; the PMP CSRs are written inside the checkers
                endcase
                wb_addr <= mem_result;
                wb_mdata <= mem_load ? loaded : stored;
                wb_raw <= dmem_rdata; wb_load <= mem_load;
                mem_valid <= ex_valid; mem_pc <= ex_pc; mem_insn <= ex_insn; mem_rd <= ex_rd; mem_wen <= ex_wen;
                mem_result <= ex_result; mem_store <= b;
                mem_code <= ex_cause; mem_tval <= ex_tval; mem_csr <= ex_csr; mem_mret <= ex_mret; mem_wfi <= ex_wfi;
                mem_csr_src <= ex_insn[14] ? {27'd0, ex_rs1} : a;
                if (ex_valid && ex_op == BRANCH)  // train the counter with the outcome
                    bht[ex_pc[5:2]] <= taken ? counter + (counter != 2'b11) : counter - (counter != 2'b00);
                if (ex_valid && (ex_op == BRANCH || ex_op == JAL || ex_op == JALR)) perf_ctrl <= perf_ctrl + 1;
                if (redirect && !ex_ebreak) perf_flush <= perf_flush + 1;
                if (redirect || load_use || !id_valid) ex_valid <= 0;
                else begin
                    ex_valid <= 1; ex_pc <= id_pc; ex_insn <= id_insn; ex_imm <= id_imm; ex_a <= rf1; ex_b <= rf2;
                    ex_rd <= id_wen ? id_insn[11:7] : 5'd0; ex_wen <= id_wen; ex_pred <= id_pred;
                    ex_code <= id_code; ex_csr <= id_csr; ex_mret <= id_mret; ex_wfi <= id_wfi;
                end
                if (redirect) id_valid <= 0;
                else if (!load_use) begin
                    id_valid <= 1; id_pc <= pc; id_insn <= if_fault ? 32'd0 : imem_data; id_pred <= if_predict; id_fault <= if_fault;
                end
                // Mutation 8 lets the prediction in IF override a redirect from EX.
                if (MUTATION == 8 && if_predict && !load_use) pc <= if_target;
                else if (redirect) pc <= resume;
                else if (!load_use) pc <= if_predict ? if_target : pc + 32'd4;
                if (mret_take) begin  // return to mepc; the younger instructions were fetched past MRET
                    st_mie <= st_mpie; st_mpie <= 1; mem_valid <= 0; ex_valid <= 0; id_valid <= 0; pc <= {epc, 2'b00};
                    // PRIV: back to the privilege in MPP, which becomes U; leaving machine mode clears MPRV.
                    if (PRIV != 0) begin priv_m <= st_mpp_m; st_mpp_m <= 0; if (!st_mpp_m) st_mprv <= 0; end
                end
                if (pmp_flush) begin mem_valid <= 0; ex_valid <= 0; id_valid <= 0; pc <= mem_pc + 32'd4; end
            end
        end
    end
endmodule
