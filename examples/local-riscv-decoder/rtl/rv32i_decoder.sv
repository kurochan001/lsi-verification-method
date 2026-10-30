// RV32I instruction decoder, written by hand from the base ISA, independently of the
// generated specification. Every word outside the RV32I table is illegal: the base ISA
// leaves reserved encodings unspecified, and this core raises illegal-instruction on them.
module rv32i_decoder #(parameter MUTATION = 0) (
    input  wire [31:0] insn,
    output reg         legal,
    output reg  [5:0]  op,        // instruction number, in the order of the riscv-opcodes table
    output reg  [31:0] imm,
    output reg         rd_we, rs1_used, rs2_used);
    localparam [5:0] LUI = 0, AUIPC = 1, JAL = 2, JALR = 3, BEQ = 4, BNE = 5, BLT = 6, BGE = 7,
                     BLTU = 8, BGEU = 9, LB = 10, LH = 11, LW = 12, LBU = 13, LHU = 14, SB = 15,
                     SH = 16, SW = 17, ADDI = 18, SLTI = 19, SLTIU = 20, XORI = 21, ORI = 22,
                     ANDI = 23, ADD = 24, SUB = 25, SLL = 26, SLT = 27, SLTU = 28, XOR = 29,
                     SRL = 30, SRA = 31, OR = 32, AND = 33, FENCE = 34, ECALL = 35, EBREAK = 36,
                     SLLI = 37, SRLI = 38, SRAI = 39;
    wire [2:0] f3 = insn[14:12];
    wire [6:0] f7 = insn[31:25];
    wire [31:0] imm_i = {{20{insn[31]}}, insn[31:20]};
    wire [31:0] imm_s = {{20{insn[31]}}, insn[31:25], insn[11:7]};
    // Mutation 4 takes bit 11 of a branch offset from the sign bit instead of insn[7].
    wire [31:0] imm_b = {{19{insn[31]}}, insn[31], MUTATION == 4 ? insn[31] : insn[7], insn[30:25], insn[11:8], 1'b0};
    wire [31:0] imm_u = {insn[31:12], 12'b0};
    wire [31:0] imm_j = {{11{insn[31]}}, insn[31], insn[19:12], insn[20], insn[30:21], 1'b0};
    // RV32 shifts need insn[31:25] exactly; mutation 1 checks insn[31:26] as RV64 does,
    // accepting shift amounts of 32 to 63.
    wire [6:0] shift_f7 = MUTATION == 1 ? {f7[6:1], 1'b0} : f7;
    // Mutation 3 tells the register operations apart by insn[30] alone, so M-extension
    // encodings such as MUL decode as RV32I operations.
    wire base_op = MUTATION == 3 ? !f7[5] : f7 == 7'b0000000;
    wire alt_op = MUTATION == 3 ? f7[5] : f7 == 7'b0100000;

    task accept(input [5:0] which, input [31:0] value, input w, r1, r2);
        begin legal = 1'b1; op = which; imm = value; rd_we = w; rs1_used = r1; rs2_used = r2; end
    endtask

    always @* begin
        legal = 1'b0; op = 6'd0; imm = 32'b0; rd_we = 1'b0; rs1_used = 1'b0; rs2_used = 1'b0;
        case (insn[6:0])
            7'b0110111: accept(LUI, imm_u, 1, 0, 0);
            7'b0010111: accept(AUIPC, imm_u, 1, 0, 0);
            7'b1101111: accept(JAL, imm_j, 1, 0, 0);
            7'b1100111: if (f3 == 3'd0) accept(JALR, imm_i, 1, 1, 0);
            7'b1100011: case (f3)
                3'd0: accept(BEQ, imm_b, 0, 1, 1);
                3'd1: accept(BNE, imm_b, 0, 1, 1);
                3'd4: accept(BLT, imm_b, 0, 1, 1);
                3'd5: accept(BGE, imm_b, 0, 1, 1);
                3'd6: accept(BLTU, imm_b, 0, 1, 1);
                3'd7: accept(BGEU, imm_b, 0, 1, 1);
                default: ;
            endcase
            7'b0000011: case (f3)
                3'd0: accept(LB, imm_i, 1, 1, 0);
                3'd1: accept(LH, imm_i, 1, 1, 0);
                3'd2: accept(LW, imm_i, 1, 1, 0);
                3'd4: accept(LBU, imm_i, 1, 1, 0);
                3'd5: accept(LHU, imm_i, 1, 1, 0);
                default: ;
            endcase
            7'b0100011: case (f3)
                3'd0: accept(SB, imm_s, 0, 1, 1);
                3'd1: accept(SH, imm_s, 0, 1, 1);
                3'd2: accept(SW, imm_s, 0, 1, 1);
                default: ;
            endcase
            7'b0010011: case (f3)
                3'd0: accept(ADDI, imm_i, 1, 1, 0);
                3'd2: accept(SLTI, imm_i, 1, 1, 0);
                3'd3: accept(SLTIU, imm_i, 1, 1, 0);
                3'd4: accept(XORI, imm_i, 1, 1, 0);
                3'd6: accept(ORI, imm_i, 1, 1, 0);
                3'd7: accept(ANDI, imm_i, 1, 1, 0);
                3'd1: if (shift_f7 == 7'b0000000) accept(SLLI, {27'b0, insn[24:20]}, 1, 1, 0);
                default: if (shift_f7 == 7'b0000000) accept(SRLI, {27'b0, insn[24:20]}, 1, 1, 0);
                         else if (shift_f7 == 7'b0100000) accept(SRAI, {27'b0, insn[24:20]}, 1, 1, 0);
            endcase
            7'b0110011: if (base_op) case (f3)
                3'd0: accept(ADD, 32'b0, 1, 1, 1);
                3'd1: accept(SLL, 32'b0, 1, 1, 1);
                3'd2: accept(SLT, 32'b0, 1, 1, 1);
                3'd3: accept(SLTU, 32'b0, 1, 1, 1);
                3'd4: accept(XOR, 32'b0, 1, 1, 1);
                3'd5: accept(SRL, 32'b0, 1, 1, 1);
                3'd6: accept(OR, 32'b0, 1, 1, 1);
                default: accept(AND, 32'b0, 1, 1, 1);
            endcase else if (alt_op) case (f3)
                3'd0: accept(SUB, 32'b0, 1, 1, 1);
                3'd5: accept(SRA, 32'b0, 1, 1, 1);
                default: ;
            endcase
            // FENCE ignores its rd and rs1 fields and treats reserved fm/pred/succ values as a
            // normal fence. Mutation 2 rejects fences whose rd or rs1 field is not zero.
            7'b0001111: if (f3 == 3'd0 && (MUTATION != 2 || insn[19:15] == 5'd0 && insn[11:7] == 5'd0))
                accept(FENCE, imm_i, 0, 0, 0);
            7'b1110011: if (insn[31:7] == 25'd0) accept(ECALL, 32'b0, 0, 0, 0);
                        else if (insn[31:7] == {12'd1, 13'd0}) accept(EBREAK, 32'b0, 0, 0, 0);
            default: ;
        endcase
    end
endmodule
