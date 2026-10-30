// Formal harness: the instruction word is a free input, so one proof covers all 2^32 words.
// The decoder is compared with the specification generated from the riscv-opcodes table.
module decoder_formal #(parameter MUTATION = 0) (input wire [31:0] insn);
    wire legal, rd_we, rs1_used, rs2_used, s_legal, s_rd_we, s_rs1_used, s_rs2_used;
    wire [5:0] op, s_index;
    wire [31:0] imm, s_imm;
    wire [39:0] hit;
    rv32i_decoder #(.MUTATION(MUTATION)) dut(.insn(insn), .legal(legal), .op(op), .imm(imm), .rd_we(rd_we),
                                             .rs1_used(rs1_used), .rs2_used(rs2_used));
    rv32i_spec spec(.insn(insn), .hit(hit), .legal(s_legal), .index(s_index), .imm(s_imm), .rd_we(s_rd_we),
                    .rs1_used(s_rs1_used), .rs2_used(s_rs2_used));
    wire [6:0] opcode = insn[6:0];
    wire is_branch = hit[`RV32I_BEQ] || hit[`RV32I_BNE] || hit[`RV32I_BLT] || hit[`RV32I_BGE] ||
                     hit[`RV32I_BLTU] || hit[`RV32I_BGEU];
    always @* begin
        // The table itself: no word may match two entries.
        ap_unique: assert((hit & (hit - 40'd1)) == 40'd0);
        ap_legal: assert(legal == s_legal);
        if (s_legal) begin
            ap_op: assert(op == s_index);
            ap_imm: assert(imm == s_imm);
            ap_regs: assert({rd_we, rs1_used, rs2_used} == {s_rd_we, s_rs1_used, s_rs2_used});
        end
        // Words worth seeing: each must be reachable for the comparison above to mean anything.
        cp_compressed: cover(insn[1:0] != 2'b11 && !legal);
        cp_fence_reserved_fields: cover(hit[`RV32I_FENCE] && insn[31:28] != 4'd0 && insn[19:15] != 5'd0 && insn[11:7] != 5'd0 && legal);
        cp_shift_rv64: cover(opcode == 7'b0010011 && insn[13:12] == 2'b01 && insn[25] && !legal);
        cp_mul: cover(opcode == 7'b0110011 && insn[31:25] == 7'b0000001 && !legal);
        cp_csr: cover(opcode == 7'b1110011 && insn[14:12] != 3'd0 && !legal);
        cp_branch_far: cover(is_branch && insn[7] != insn[31] && legal);
    end
endmodule
