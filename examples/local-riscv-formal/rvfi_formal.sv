// Retirement interface in the style of RVFI around rv32i_core (TRAPS = 0), and the checks on it.
// The core is not changed. What its retirement port does not show is rebuilt here from what can
// be observed outside the core: the data bus gives the memory access and the register values an
// instruction read (address base, store data); the pc of the next retirement gives pc_wdata.
// The expected results are written from the instruction word alone, per instruction group.
// CLASS narrows the result check to one group of operations (0 all, 1 upper immediate and link,
// 2 add and subtract, 3 logic, 4 shifts, 5 comparisons), as riscv-formal checks one instruction per run.
// CHECK selects the groups of assertions (1 result, 2 memory access, 4 register consistency, 8 pc
// chain); the others are not compiled. SIMPLE = 1 keeps shifts and comparisons out of the program, for the deeper tasks.
module rvfi_formal #(parameter PREDICT = 0, MUTATION = 0, CHECK = 15, CLASS = 0, SIMPLE = 0, REGS = 32, NO_WAIT = 0, LOCK_RESET = 0) (input wire clk);
    (* anyseq *) wire [31:0] imem_data;
    (* anyseq *) wire [31:0] dmem_rdata;
    (* anyseq *) wire        dmem_ready_any;
    // Two registers, chosen freely once, are followed through the run: every pair is covered.
    (* anyconst *) wire [4:0] track, track_b;
    reg init = 1'b1;
    always @(posedge clk) init <= 1'b0;
    wire rst_n = !init && LOCK_RESET == 0;
    wire dmem_ready = dmem_ready_any || NO_WAIT != 0;

    wire [31:0] imem_addr, dmem_addr, dmem_wdata;
    wire [3:0]  dmem_be;
    wire        dmem_valid, dmem_we, ret_valid, halted;
    wire [31:0] ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data, perf_ctrl, perf_flush;
    wire [4:0]  ret_rd;
    wire [1:0]  ret_mem;
    rv32i_core #(.MUTATION(MUTATION), .PREDICT(PREDICT), .TRAPS(0)) core (
        .clk(clk), .rst_n(rst_n), .irq(1'b0), .imem_addr(imem_addr), .imem_data(imem_data),
        .dmem_valid(dmem_valid), .dmem_we(dmem_we), .dmem_addr(dmem_addr), .dmem_wdata(dmem_wdata),
        .dmem_be(dmem_be), .dmem_rdata(dmem_rdata), .dmem_ready(dmem_ready),
        .ret_valid(ret_valid), .ret_pc(ret_pc), .ret_insn(ret_insn), .ret_wdata(ret_wdata),
        .ret_mem_addr(ret_mem_addr), .ret_mem_data(ret_mem_data), .ret_rd(ret_rd), .ret_mem(ret_mem),
        .perf_ctrl(perf_ctrl), .perf_flush(perf_flush), .halted(halted));

    // ---- The instruction set of the contract: RV32I without FENCE, ECALL and CSRs. ----
    function automatic legal(input [31:0] i);
        reg [6:0] op, f7; reg [2:0] f3;
        begin
            op = i[6:0]; f3 = i[14:12]; f7 = i[31:25];
            case (op)
                7'b0110111, 7'b0010111: legal = 1'b1;                       // LUI, AUIPC
                7'b1101111: legal = !i[21];                                 // JAL to a multiple of 4
                7'b1100111: legal = f3 == 3'd0;                             // JALR
                7'b1100011: legal = f3 != 3'd2 && f3 != 3'd3 && !i[8];      // branches to a multiple of 4
                7'b0000011: legal = f3 == 3'd0 || f3 == 3'd1 || f3 == 3'd2 || f3 == 3'd4 || f3 == 3'd5;
                7'b0100011: legal = f3 == 3'd0 || f3 == 3'd1 || f3 == 3'd2;
                7'b0010011: legal = f3 == 3'd1 ? f7 == 7'd0 : f3 == 3'd5 ? (f7 == 7'd0 || f7 == 7'h20) : 1'b1;
                7'b0110011: legal = f7 == 7'd0 || (f7 == 7'h20 && (f3 == 3'd0 || f3 == 3'd5));
                7'b1110011: legal = i == 32'h00100073;                      // EBREAK
                default:    legal = 1'b0;
            endcase
        end
    endfunction
    function automatic simple(input [31:0] i);
        simple = !((i[6:0] == 7'b0010011 || i[6:0] == 7'b0110011) &&
                   (i[14:12] == 3'd1 || i[14:12] == 3'd2 || i[14:12] == 3'd3 || i[14:12] == 3'd5));
    endfunction
    // REGS < 32 keeps the program to the registers x0 .. x(REGS-1), which shortens the search.
    function automatic few(input [31:0] i);
        few = REGS >= 32 || ({27'd0, i[11:7]} < REGS && {27'd0, i[19:15]} < REGS && {27'd0, i[24:20]} < REGS);
    endfunction
    // Integer operations, selected by funct3 and the "alternate" bit (SUB, SRA, SRAI).
    function automatic [31:0] compute(input [2:0] f3, input alt, input [31:0] x, input [31:0] y);
        reg signed [31:0] sx, sy;
        begin
            sx = x; sy = y;
            case ({alt, f3})
                4'b0000: compute = x + y;
                4'b1000: compute = x - y;
                4'b0001: compute = x << y[4:0];
                4'b0010: compute = sx < sy ? 32'd1 : 32'd0;
                4'b0011: compute = x < y ? 32'd1 : 32'd0;
                4'b0100: compute = x ^ y;
                4'b0101: compute = x >> y[4:0];
                4'b1101: compute = sx >>> y[4:0];
                4'b0110: compute = x | y;
                4'b0111: compute = x & y;
                default: compute = 32'd0;
            endcase
        end
    endfunction
    function automatic branches(input [2:0] f3, input [31:0] x, input [31:0] y);
        reg signed [31:0] sx, sy;
        begin
            sx = x; sy = y;
            case (f3)
                3'd0: branches = x == y;
                3'd1: branches = x != y;
                3'd4: branches = sx < sy;
                3'd5: branches = !(sx < sy);
                3'd6: branches = x < y;
                default: branches = !(x < y);
            endcase
        end
    endfunction

    // ---- The retiring instruction. ----
    // The core is reset synchronously: before its first clock edge in reset, ret_valid is not defined.
    wire        rvfi_valid = ret_valid && !init;
    wire [31:0] rvfi_insn = ret_insn, rvfi_pc_rdata = ret_pc;
    wire [4:0]  rvfi_rd_addr = ret_rd;
    wire [31:0] rvfi_rd_wdata = ret_wdata;
    wire [6:0]  op = rvfi_insn[6:0];
    wire [2:0]  f3 = rvfi_insn[14:12];
    wire is_lui = op == 7'b0110111, is_auipc = op == 7'b0010111, is_jal = op == 7'b1101111;
    wire is_jalr = op == 7'b1100111, is_branch = op == 7'b1100011, is_load = op == 7'b0000011;
    wire is_store = op == 7'b0100011, is_opimm = op == 7'b0010011, is_op = op == 7'b0110011;
    wire is_ebreak = rvfi_insn == 32'h00100073;
    wire [31:0] imm_i = {{20{rvfi_insn[31]}}, rvfi_insn[31:20]};
    wire [31:0] imm_s = {{20{rvfi_insn[31]}}, rvfi_insn[31:25], rvfi_insn[11:7]};
    wire [31:0] imm_b = {{19{rvfi_insn[31]}}, rvfi_insn[31], rvfi_insn[7], rvfi_insn[30:25], rvfi_insn[11:8], 1'b0};
    wire [31:0] imm_u = {rvfi_insn[31:12], 12'd0};
    wire [31:0] imm_j = {{11{rvfi_insn[31]}}, rvfi_insn[31], rvfi_insn[19:12], rvfi_insn[20], rvfi_insn[30:21], 1'b0};
    wire uses_rs1 = is_jalr || is_branch || is_load || is_store || is_opimm || is_op;
    wire uses_rs2 = is_branch || is_store || is_op;
    wire [4:0] rvfi_rs1_addr = uses_rs1 ? rvfi_insn[19:15] : 5'd0;
    wire [4:0] rvfi_rs2_addr = uses_rs2 ? rvfi_insn[24:20] : 5'd0;
    wire writes_rd = is_lui || is_auipc || is_jal || is_jalr || is_load || is_opimm || is_op;

    // ---- The followed registers, rebuilt from the retirements. A register is "known" once an
    // instruction has retired writing it: the core does not reset its registers. ----
    reg track_known = 1'b0, track_b_known = 1'b0;
    reg [31:0] track_value, track_b_value;
    wire rs1_known = rvfi_rs1_addr == 5'd0 || (rvfi_rs1_addr == track && track_known) || (rvfi_rs1_addr == track_b && track_b_known);
    wire rs2_known = rvfi_rs2_addr == 5'd0 || (rvfi_rs2_addr == track && track_known) || (rvfi_rs2_addr == track_b && track_b_known);
    wire [31:0] rs1_value = rvfi_rs1_addr == 5'd0 ? 32'd0 : rvfi_rs1_addr == track ? track_value : track_b_value;
    wire [31:0] rs2_value = rvfi_rs2_addr == 5'd0 ? 32'd0 : rvfi_rs2_addr == track ? track_value : track_b_value;

    // ---- The data bus transfer of the previous cycle: it belongs to the instruction retiring now. ----
    reg        bus_seen = 1'b0, bus_we;
    reg [31:0] bus_addr, bus_wdata, bus_rdata;
    reg [3:0]  bus_be;
    always @(posedge clk) begin
        bus_seen <= rst_n && dmem_valid && dmem_ready;
        bus_we <= dmem_we; bus_addr <= dmem_addr; bus_wdata <= dmem_wdata; bus_rdata <= dmem_rdata; bus_be <= dmem_be;
    end
    wire [31:0] rvfi_mem_addr = bus_addr;
    wire [1:0]  lane = rvfi_mem_addr[1:0];
    wire [1:0]  size = f3[1:0];                                    // 0 byte, 1 halfword, 2 word
    wire aligned = size == 2'd0 || (size == 2'd1 && !lane[0]) || (size == 2'd2 && lane == 2'd0);
    wire [3:0] lanes = size == 2'd0 ? 4'b0001 << lane : size == 2'd1 ? 4'b0011 << lane : 4'b1111;
    wire [3:0] rvfi_mem_rmask = is_load ? lanes : 4'd0;
    wire [3:0] rvfi_mem_wmask = is_store ? lanes : 4'd0;
    wire [31:0] shifted = bus_rdata >> {lane, 3'd0};
    wire [31:0] rvfi_mem_rdata = size == 2'd0 ? {{24{!f3[2] && shifted[7]}}, shifted[7:0]} :
                                 size == 2'd1 ? {{16{!f3[2] && shifted[15]}}, shifted[15:0]} : shifted;
    wire [31:0] store_mask = {{8{lanes[3]}}, {8{lanes[2]}}, {8{lanes[1]}}, {8{lanes[0]}}};
    wire [31:0] rvfi_mem_wdata = rs2_value << {lane, 3'd0};
    // Register values the instruction really read, where they can be seen from outside.
    wire seen_rs1 = (is_load || is_store) && bus_seen;
    wire [31:0] rvfi_rs1_rdata = bus_addr - (is_store ? imm_s : imm_i);
    wire seen_rs2 = is_store && size == 2'd2 && bus_seen;
    wire [31:0] rvfi_rs2_rdata = bus_wdata;

    // ---- Expected result and next pc, from the instruction word and the rebuilt registers. ----
    wire alt = rvfi_insn[30] && (is_op || (is_opimm && f3 == 3'd5));
    wire [31:0] spec_rd_wdata = is_lui ? imm_u : is_auipc ? rvfi_pc_rdata + imm_u :
                                is_jal || is_jalr ? rvfi_pc_rdata + 32'd4 :
                                compute(f3, alt, rs1_value, is_op ? rs2_value : imm_i);
    wire spec_value_known = is_lui || is_auipc || is_jal || is_jalr || (is_opimm && rs1_known) || (is_op && rs1_known && rs2_known);
    wire arith = is_op || is_opimm;
    wire in_class = CLASS == 0 || (CLASS == 1 && !arith) || (CLASS == 2 && arith && f3 == 3'd0) ||
                    (CLASS == 3 && arith && (f3 == 3'd4 || f3 == 3'd6 || f3 == 3'd7)) ||
                    (CLASS == 4 && arith && (f3 == 3'd1 || f3 == 3'd5)) || (CLASS == 5 && arith && (f3 == 3'd2 || f3 == 3'd3));
    wire [4:0] spec_rd_addr = writes_rd ? rvfi_insn[11:7] : 5'd0;
    wire [31:0] spec_pc_wdata = is_jal ? rvfi_pc_rdata + imm_j : is_jalr ? (rs1_value + imm_i) & 32'hfffffffe :
                                is_branch && branches(f3, rs1_value, rs2_value) ? rvfi_pc_rdata + imm_b : rvfi_pc_rdata + 32'd4;
    wire spec_pc_known = is_jalr ? rs1_known : is_branch ? rs1_known && rs2_known : 1'b1;

    reg [31:0] rvfi_order = 32'd0, next_pc;
    reg next_pc_known = 1'b0, first = 1'b1, stopped = 1'b0;
    // history for the cover goals
    reg prev_valid = 1'b0, prev_load, prev2_valid = 1'b0, waited = 1'b0;
    reg [4:0] prev_rd, prev2_rd;
    reg [31:0] last_pc;
    always @(posedge clk) begin
        if (rst_n && dmem_valid && !dmem_ready) waited <= 1'b1;
        if (rvfi_valid) begin
            rvfi_order <= rvfi_order + 32'd1; first <= 1'b0; last_pc <= rvfi_pc_rdata;
            next_pc <= spec_pc_wdata; next_pc_known <= spec_pc_known;
            if (is_ebreak) stopped <= 1'b1;
            if (rvfi_rd_addr != 5'd0 && rvfi_rd_addr == track) begin track_known <= 1'b1; track_value <= rvfi_rd_wdata; end
            if (rvfi_rd_addr != 5'd0 && rvfi_rd_addr == track_b) begin track_b_known <= 1'b1; track_b_value <= rvfi_rd_wdata; end
            prev_valid <= 1'b1; prev_load <= is_load; prev_rd <= rvfi_rd_addr;
            prev2_valid <= prev_valid; prev2_rd <= prev_rd;
        end
    end

    always @(posedge clk) as_legal: assume(legal(imem_data) && (SIMPLE == 0 || simple(imem_data)) && few(imem_data));

    // Each group exists only in the tasks that select it, so that the compiled model can be
    // compared with the list of assertions a task is planned to check.
    generate if (CHECK & 1) begin : g_result      // (1) the result of the instruction itself
        always @(posedge clk) if (!init && rvfi_valid) begin
            ap_rd_addr: assert(rvfi_rd_addr == spec_rd_addr && (rvfi_rd_addr != 5'd0 || rvfi_rd_wdata == 32'd0));
            if (in_class && spec_value_known && rvfi_rd_addr != 5'd0) ap_rd_value: assert(rvfi_rd_wdata == spec_rd_wdata);
        end
    end endgenerate
    generate if (CHECK & 2) begin : g_memory      // (1) its memory access, seen on the bus
        always @(posedge clk) if (!init) begin
            // Every data transfer belongs to the load or store retiring one cycle later, and a
            // retiring load or store had exactly that transfer.
            ap_bus: assert(bus_seen == (rvfi_valid && (is_load || is_store)) && (!bus_seen || bus_we == is_store));
            if (rvfi_valid && is_load && bus_seen && aligned)
                ap_load: assert((rvfi_rd_addr == 5'd0 || rvfi_rd_wdata == rvfi_mem_rdata) && ret_mem == 2'd1 &&
                                ret_mem_addr == rvfi_mem_addr && ret_mem_data == rvfi_mem_rdata);
            if (rvfi_valid && is_store && bus_seen && aligned)
                ap_store: assert(bus_be == rvfi_mem_wmask && ret_mem == 2'd2 && ret_mem_addr == rvfi_mem_addr &&
                                 (!rs2_known || ((bus_wdata ^ rvfi_mem_wdata) & store_mask) == 32'd0));
            if (rvfi_valid && (is_load || is_store) && bus_seen && rs1_known)
                ap_mem_addr: assert(rvfi_mem_addr == rs1_value + (is_store ? imm_s : imm_i));
        end
    end endgenerate
    generate if (CHECK & 4) begin : g_register    // (2) a read returns the latest value written
        always @(posedge clk) if (!init && rvfi_valid) begin
            if (seen_rs1 && rvfi_rs1_addr == track)
                ap_reg_rs1: assert(track == 5'd0 ? rvfi_rs1_rdata == 32'd0 : !track_known || rvfi_rs1_rdata == track_value);
            if (seen_rs2 && rvfi_rs2_addr == track)
                ap_reg_rs2: assert(track == 5'd0 ? rvfi_rs2_rdata == 32'd0 : !track_known || rvfi_rs2_rdata == track_value);
        end
    end endgenerate
    generate if (CHECK & 8) begin : g_pc          // (3) the pc chain, (4) nothing after the halt
        always @(posedge clk) if (!init) begin
            ap_halt: assert(!(stopped && rvfi_valid));
            if (rvfi_valid && first) ap_pc_first: assert(rvfi_pc_rdata == 32'd0);
            if (rvfi_valid && !first && next_pc_known) ap_pc_chain: assert(rvfi_pc_rdata == next_pc);
        end
    end endgenerate

    // Reachability: every instruction group and the pipeline situations the checks are for.
    always @(posedge clk) begin
        cp_lui:        cover(rvfi_valid && is_lui && rvfi_rd_addr != 5'd0);
        cp_auipc:      cover(rvfi_valid && is_auipc && rvfi_rd_addr != 5'd0);
        cp_jal:        cover(rvfi_valid && is_jal && rvfi_order != 32'd0);
        cp_jalr:       cover(rvfi_valid && is_jalr && rs1_known && rvfi_rs1_addr != 5'd0);
        cp_taken:      cover(rvfi_valid && !first && next_pc_known && is_op && last_pc + 32'd4 != rvfi_pc_rdata);
        cp_not_taken:  cover(rvfi_valid && is_branch && rs1_known && rs2_known && rvfi_rs1_addr != 5'd0 && !branches(f3, rs1_value, rs2_value));
        cp_load:       cover(rvfi_valid && is_load && f3 == 3'd1 && rvfi_rd_addr != 5'd0 && lane == 2'd2);
        cp_store:      cover(rvfi_valid && is_store && f3 == 3'd0 && rs2_known && rvfi_rs2_addr != 5'd0 && lane == 2'd3);
        cp_opimm:      cover(rvfi_valid && is_opimm && rs1_known && rvfi_rs1_addr != 5'd0 && rvfi_rd_addr != 5'd0);
        cp_op:         cover(rvfi_valid && is_op && rs1_known && rs2_known && rvfi_rs1_addr != 5'd0 && rvfi_rs2_addr != 5'd0 && rvfi_rs1_addr != rvfi_rs2_addr);
        cp_forward1:   cover(rvfi_valid && is_op && prev_valid && !prev_load && prev_rd != 5'd0 && rvfi_rs1_addr == prev_rd);
        cp_forward2:   cover(rvfi_valid && is_op && prev2_valid && prev2_rd != 5'd0 && rvfi_rs2_addr == prev2_rd && prev_rd != prev2_rd);
        cp_load_use:   cover(rvfi_valid && is_opimm && prev_valid && prev_load && prev_rd != 5'd0 && rvfi_rs1_addr == prev_rd);
        cp_reg_read:   cover(rvfi_valid && seen_rs2 && track != 5'd0 && track_known && rvfi_rs2_addr == track);
        cp_halt:       cover(stopped && rvfi_order >= 32'd3);
    end
    generate if (NO_WAIT == 0) begin : g_wait
        always @(posedge clk) cp_wait: cover(rvfi_valid && is_store && waited);
    end endgenerate
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused = &{1'b0, imem_addr, perf_ctrl, perf_flush, halted, rvfi_mem_rmask, imm_b[0], imm_j[0]};
    /* verilator lint_on UNUSEDSIGNAL */
endmodule
