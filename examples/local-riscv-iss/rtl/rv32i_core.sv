// Five-stage RV32I pipeline: word loads and stores only, no CSRs or traps, EBREAK halts.
// Results are forwarded from EX/MEM and MEM/WB, the register file passes a value written in
// the same cycle, a load followed by its use costs one bubble, and branches and jumps are
// resolved in EX, flushing the two younger instructions. While data memory waits, every
// stage holds and WB receives a bubble. The retirement port shows each instruction that
// leaves WB, for comparison with an instruction set simulator.
module rv32i_core #(parameter MUTATION = 0) (
    input  wire        clk, rst_n,
    output wire [31:0] imem_addr,
    input  wire [31:0] imem_data,
    output wire        dmem_valid, dmem_we,
    output wire [31:0] dmem_addr, dmem_wdata,
    input  wire [31:0] dmem_rdata,
    input  wire        dmem_ready,
    output wire        ret_valid,
    output wire [31:0] ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data,
    output wire [4:0]  ret_rd,
    output wire [1:0]  ret_mem,
    output reg         halted);
    localparam [6:0] LUI = 7'h37, AUIPC = 7'h17, JAL = 7'h6f, JALR = 7'h67, BRANCH = 7'h63,
                     LOAD = 7'h03, STORE = 7'h23, OPIMM = 7'h13, OP = 7'h33;
    localparam [31:0] EBREAK = 32'h00100073;

    reg [31:0] pc;
    reg [31:0] regs [1:31];
    reg id_valid, ex_valid, ex_wen, mem_valid, mem_wen, wb_valid, wb_wen;
    reg [31:0] id_pc, id_insn, ex_pc, ex_insn, ex_imm, ex_a, ex_b;
    reg [31:0] mem_pc, mem_insn, mem_result, mem_store, wb_pc, wb_insn, wb_data, wb_addr, wb_mdata;
    reg [4:0] ex_rd, mem_rd, wb_rd;
    reg [1:0] wb_mem;
    assign imem_addr = pc;

    // ID: decode and read registers.
    wire [6:0] id_op = id_insn[6:0];
    wire [4:0] id_rs1 = id_insn[19:15], id_rs2 = id_insn[24:20];
    wire id_use1 = id_op == JALR || id_op == BRANCH || id_op == LOAD || id_op == STORE || id_op == OPIMM || id_op == OP;
    wire id_use2 = id_op == BRANCH || id_op == STORE || id_op == OP;
    wire id_wen = id_op == LUI || id_op == AUIPC || id_op == JAL || id_op == JALR || id_op == LOAD ||
                  id_op == OPIMM || id_op == OP;
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
    wire load_use = MUTATION != 2 && id_valid && ex_valid && ex_insn[6:0] == LOAD && ex_rd != 0 &&
                    ((id_use1 && id_rs1 == ex_rd) || (id_use2 && id_rs2 == ex_rd));

    // EX: forward, compute, resolve branches. The younger producer (EX/MEM) wins.
    // Mutation 1 also forwards results addressed to x0.
    wire [6:0] ex_op = ex_insn[6:0];
    wire [2:0] ex_f3 = ex_insn[14:12];
    wire [4:0] ex_rs1 = ex_insn[19:15], ex_rs2 = ex_insn[24:20];
    wire mem_fwd_ok = mem_valid && mem_wen && (mem_rd != 0 || MUTATION == 1);
    wire wb_fwd_ok = wb_valid && wb_wen && (wb_rd != 0 || MUTATION == 1);
    wire [31:0] a = mem_fwd_ok && mem_rd == ex_rs1 ? mem_result : wb_fwd_ok && wb_rd == ex_rs1 ? wb_data : ex_a;
    wire [31:0] b = mem_fwd_ok && mem_rd == ex_rs2 ? mem_result : wb_fwd_ok && wb_rd == ex_rs2 ? wb_data : ex_b;
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
    wire taken = ex_valid && (ex_op == JAL || ex_op == JALR || (ex_op == BRANCH && cond) || ex_ebreak);
    wire [31:0] target = ex_op == JALR ? (jalr_base + ex_imm) & ~32'd1 : ex_ebreak ? ex_pc : ex_pc + ex_imm;
    wire [31:0] ex_result = ex_op == LUI ? ex_imm : ex_op == AUIPC ? ex_pc + ex_imm :
                            ex_op == JAL || ex_op == JALR ? ex_pc + 32'd4 :
                            ex_op == LOAD || ex_op == STORE ? a + ex_imm : alu;

    // MEM: one word access; the pipeline freezes until the memory is ready.
    wire mem_load = mem_insn[6:0] == LOAD, mem_st = mem_insn[6:0] == STORE;
    assign dmem_valid = mem_valid && (mem_load || mem_st) && !halted;
    assign dmem_we = mem_st;
    assign dmem_addr = mem_result;
    assign dmem_wdata = mem_store;
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
            pc <= 0; halted <= 0;
            id_valid <= 0; ex_valid <= 0; mem_valid <= 0; wb_valid <= 0;
        end else if (!halted) begin
            if (wb_write) regs[wb_rd] <= wb_data;
            if (wb_valid && wb_insn == EBREAK) halted <= 1;
            if (freeze) begin
                // The instruction in WB retires and its forwarding source is gone next cycle,
                // so EX keeps the forwarded operands. Mutation 4 does not.
                wb_valid <= 0;
                if (MUTATION != 4) begin ex_a <= a; ex_b <= b; end
            end else begin
                wb_valid <= mem_valid; wb_pc <= mem_pc; wb_insn <= mem_insn; wb_rd <= mem_rd; wb_wen <= mem_wen;
                wb_data <= mem_load ? dmem_rdata : mem_result;
                wb_mem <= mem_load ? 2'd1 : mem_st ? 2'd2 : 2'd0;
                wb_addr <= mem_result;
                wb_mdata <= mem_load ? dmem_rdata : mem_store;
                mem_valid <= ex_valid; mem_pc <= ex_pc; mem_insn <= ex_insn; mem_rd <= ex_rd; mem_wen <= ex_wen;
                mem_result <= ex_result; mem_store <= b;
                if (taken || load_use || !id_valid) ex_valid <= 0;
                else begin
                    ex_valid <= 1; ex_pc <= id_pc; ex_insn <= id_insn; ex_imm <= id_imm; ex_a <= rf1; ex_b <= rf2;
                    ex_rd <= id_wen ? id_insn[11:7] : 5'd0; ex_wen <= id_wen;
                end
                if (taken) id_valid <= 0;
                else if (!load_use) begin id_valid <= 1; id_pc <= pc; id_insn <= imem_data; end
                if (taken) pc <= target;
                else if (!load_use) pc <= pc + 32'd4;
            end
        end
    end
endmodule
