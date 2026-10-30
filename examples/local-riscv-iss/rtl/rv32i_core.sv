// Five-stage RV32I pipeline: aligned loads and stores of bytes, halfwords and words, EBREAK
// halts. TRAPS adds machine-mode CSRs, exceptions, an external interrupt and MRET (see MEM).
// Results are forwarded from EX/MEM and MEM/WB, the register file passes a value written in
// the same cycle, a load followed by its use costs one bubble, and branches and jumps are
// resolved in EX, flushing the two younger instructions. While data memory waits, every
// stage holds and WB receives a bubble. The retirement port shows each instruction that
// leaves WB, for comparison with an instruction set simulator. PREDICT adds branch
// prediction in IF (see below); the default 0 fetches sequentially.
module rv32i_core #(parameter MUTATION = 0, PREDICT = 0, TRAPS = 0) (
    input  wire        clk, rst_n,
    input  wire        irq,                     // machine external interrupt line (TRAPS)
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
    output reg         halted);
    localparam [6:0] LUI = 7'h37, AUIPC = 7'h17, JAL = 7'h6f, JALR = 7'h67, BRANCH = 7'h63,
                     LOAD = 7'h03, STORE = 7'h23, OPIMM = 7'h13, OP = 7'h33;
    localparam [6:0] SYSTEM = 7'h73;
    localparam [31:0] EBREAK = 32'h00100073, ECALL = 32'h00000073, MRET = 32'h30200073;

    reg [31:0] pc;
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
    integer i;
    assign imem_addr = pc;

    // IF: prediction. PREDICT 1 predicts JAL and backward branches taken; PREDICT 2 predicts JAL
    // taken and branches from 16 two-bit counters indexed by pc[5:2]. Targets come from the
    // fetched word itself; JALR and EBREAK are never predicted.
    wire [6:0] if_op = imem_data[6:0];
    wire [31:0] if_bimm = {{20{imem_data[31]}}, imem_data[7], imem_data[30:25], imem_data[11:8], 1'b0};
    wire [31:0] if_jimm = {{12{imem_data[31]}}, imem_data[19:12], imem_data[20], imem_data[30:21], 1'b0};
    reg [1:0] bht [0:15];
    // Mutation 7 predicts forward branches taken and backward ones not taken.
    wire if_backward = MUTATION == 7 ? !imem_data[31] : imem_data[31];
    wire if_predict = PREDICT != 0 && (if_op == JAL || (if_op == BRANCH && (PREDICT == 1 ? if_backward : bht[pc[5:2]][1])));
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
    wire id_csr = TRAPS != 0 && id_op == SYSTEM && id_insn[13:12] != 2'd0 && id_csr_known;
    wire id_mret = TRAPS != 0 && id_insn == MRET;
    wire [3:0] id_code = TRAPS == 0 ? 4'd0 : !(dec_legal || id_csr || id_mret) ? 4'd2 : id_insn == ECALL ? 4'd11 : 4'd0;
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
    wire wb_write = wb_valid && wb_wen && wb_rd != 0 && !halted;
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
    wire [31:0] ex_tval = ex_code == 4'd2 ? ex_insn : ex_misaligned ? ex_result : 32'd0;

    // MEM: one word access; the pipeline freezes until the memory is ready.
    wire mem_load = mem_insn[6:0] == LOAD, mem_st = mem_insn[6:0] == STORE;
    // Traps, MRET and CSR writes all take effect in MEM, where every older instruction has
    // finished and no younger one has changed memory or a CSR, so exceptions are precise. An
    // interrupt is taken before the first instruction to reach MEM once it is pending and
    // enabled; mutation 14 ignores mstatus.MIE.
    wire irq_take = TRAPS != 0 && mem_valid && irq && (st_mie || MUTATION == 14) && ie_meie;
    wire exc_take = TRAPS != 0 && mem_valid && mem_code != 4'd0;
    wire trap = irq_take || exc_take;
    wire mret_take = mem_valid && mem_mret && !trap;
    wire [31:0] trap_cause = irq_take ? 32'h8000000b : {28'd0, mem_code};
    reg [31:0] csr_old;
    always @* case (mem_insn[31:20])
        12'h300: csr_old = {19'd0, 2'b11, 3'd0, st_mpie, 3'd0, st_mie, 3'd0};  // mstatus, MPP = M
        12'h304: csr_old = {20'd0, ie_meie, 11'd0};                              // mie
        12'h305: csr_old = {tvec, 2'b00};                                        // mtvec, direct mode
        12'h340: csr_old = scratch;
        12'h341: csr_old = {epc, 2'b00};
        12'h342: csr_old = cause;
        12'h343: csr_old = tval;
        default: csr_old = {20'd0, irq, 11'd0};                                  // mip, read-only here
    endcase
    // CSRRW writes always; CSRRS/CSRRC (and the immediate forms) write only with a nonzero rs1.
    wire csr_we = mem_valid && mem_csr && (mem_insn[13:12] == 2'd1 || mem_insn[19:15] != 5'd0);
    wire [31:0] csr_new = mem_insn[13:12] == 2'd1 ? mem_csr_src : mem_insn[13:12] == 2'd2 ? csr_old | mem_csr_src :
                          csr_old & ~mem_csr_src;
    assign dmem_valid = mem_valid && (mem_load || mem_st) && !halted && !trap;
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
    wire freeze = dmem_valid && !dmem_ready;

    // WB: retire.
    assign ret_valid = wb_valid && !halted;
    assign ret_pc = wb_pc;
    assign ret_insn = wb_insn;
    assign ret_rd = wb_write ? wb_rd : 5'd0;
    assign ret_wdata = wb_write ? wb_data : 32'd0;
    assign ret_mem = wb_mem;
    assign ret_mem_addr = wb_addr;
    assign ret_mem_data = wb_mdata;

    always @(posedge clk) begin
        if (!rst_n) begin
            pc <= 0; halted <= 0; wb_trap <= 0;
            id_valid <= 0; ex_valid <= 0; mem_valid <= 0; wb_valid <= 0;
            st_mie <= 0; st_mpie <= 0; ie_meie <= 0; tvec <= 0; epc <= 0; scratch <= 0; cause <= 0; tval <= 0;
            perf_ctrl <= 0; perf_flush <= 0;
            for (i = 0; i < 16; i = i + 1) bht[i] <= 2'b01;  // weakly not taken
        end else if (!halted) begin
            if (wb_write) regs[wb_rd] <= wb_data;
            if (wb_valid && !wb_trap && wb_insn == EBREAK) halted <= 1;
            if (trap) begin
                // The instruction in MEM leaves as a trap record (kind 3: cause, trap value) and
                // everything younger is discarded. Mutation 15 lets a faulting load still write rd;
                // mutation 13 saves the next pc for an exception.
                wb_valid <= 1; wb_pc <= mem_pc; wb_insn <= mem_insn; wb_rd <= mem_rd; wb_trap <= 1; wb_load <= 0;
                wb_wen <= MUTATION == 15 && exc_take && mem_wen; wb_data <= mem_result;
                wb_mem <= 2'd3; wb_addr <= trap_cause; wb_mdata <= irq_take ? 32'd0 : mem_tval;
                mem_valid <= 0; ex_valid <= 0; id_valid <= 0;
                pc <= {tvec, 2'b00};
                epc <= MUTATION == 13 && !irq_take ? mem_pc[31:2] + 30'd1 : mem_pc[31:2];
                cause <= trap_cause; tval <= irq_take ? 32'd0 : mem_tval; st_mpie <= st_mie; st_mie <= 0;
            end else if (freeze) begin
                // The instruction in WB retires and its forwarding source is gone next cycle,
                // so EX keeps the forwarded operands. Mutation 4 does not.
                wb_valid <= 0;
                if (MUTATION != 4) begin ex_a <= a; ex_b <= b; end
            end else begin
                wb_valid <= mem_valid; wb_pc <= mem_pc; wb_insn <= mem_insn; wb_rd <= mem_rd; wb_wen <= mem_wen;
                wb_data <= mem_load ? loaded : mem_csr ? csr_old : mem_result; wb_trap <= 0;
                wb_mem <= mem_load ? 2'd1 : mem_st ? 2'd2 : 2'd0;
                if (csr_we) case (mem_insn[31:20])
                    12'h300: begin st_mie <= csr_new[3]; st_mpie <= csr_new[7]; end
                    12'h304: ie_meie <= csr_new[11];
                    12'h305: tvec <= csr_new[31:2];
                    12'h340: scratch <= csr_new;
                    12'h341: epc <= csr_new[31:2];
                    12'h342: cause <= csr_new;
                    12'h343: tval <= csr_new;
                    default: ;  // mip: writes are ignored
                endcase
                wb_addr <= mem_result;
                wb_mdata <= mem_load ? loaded : stored;
                wb_raw <= dmem_rdata; wb_load <= mem_load;
                mem_valid <= ex_valid; mem_pc <= ex_pc; mem_insn <= ex_insn; mem_rd <= ex_rd; mem_wen <= ex_wen;
                mem_result <= ex_result; mem_store <= b;
                mem_code <= ex_cause; mem_tval <= ex_tval; mem_csr <= ex_csr; mem_mret <= ex_mret;
                mem_csr_src <= ex_insn[14] ? {27'd0, ex_rs1} : a;
                if (ex_valid && ex_op == BRANCH)  // train the counter with the outcome
                    bht[ex_pc[5:2]] <= taken ? counter + (counter != 2'b11) : counter - (counter != 2'b00);
                if (ex_valid && (ex_op == BRANCH || ex_op == JAL || ex_op == JALR)) perf_ctrl <= perf_ctrl + 1;
                if (redirect && !ex_ebreak) perf_flush <= perf_flush + 1;
                if (redirect || load_use || !id_valid) ex_valid <= 0;
                else begin
                    ex_valid <= 1; ex_pc <= id_pc; ex_insn <= id_insn; ex_imm <= id_imm; ex_a <= rf1; ex_b <= rf2;
                    ex_rd <= id_wen ? id_insn[11:7] : 5'd0; ex_wen <= id_wen; ex_pred <= id_pred;
                    ex_code <= id_code; ex_csr <= id_csr; ex_mret <= id_mret;
                end
                if (redirect) id_valid <= 0;
                else if (!load_use) begin id_valid <= 1; id_pc <= pc; id_insn <= imem_data; id_pred <= if_predict; end
                // Mutation 8 lets the prediction in IF override a redirect from EX.
                if (MUTATION == 8 && if_predict && !load_use) pc <= if_target;
                else if (redirect) pc <= resume;
                else if (!load_use) pc <= if_predict ? if_target : pc + 32'd4;
                if (mret_take) begin  // return to mepc; the younger instructions were fetched past MRET
                    st_mie <= st_mpie; st_mpie <= 1; mem_valid <= 0; ex_valid <= 0; id_valid <= 0; pc <= {epc, 2'b00};
                end
            end
        end
    end
endmodule
