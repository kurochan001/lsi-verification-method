`timescale 1ns/1ps
// Prints the decoder's outputs for each instruction word of a file, one line per word.
module decoder_tb;
    parameter MUTATION = 0;
    reg [31:0] insn = 0;
    wire legal, rd_we, rs1_used, rs2_used;
    wire [5:0] op;
    wire [31:0] imm;
    rv32i_decoder #(.MUTATION(MUTATION)) dut(.*);
    integer fd, n;
    string words;
    initial begin
        if (!$value$plusargs("WORDS=%s", words)) $fatal(1, "WORDS required");
        fd = $fopen(words, "r"); if (!fd) $fatal(1, "words missing");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h\n", insn);
            if (n != 1) $fatal(1, "bad word");
            #1 $display("%h %b %0d %h %b%b%b", insn, legal, op, imm, rd_we, rs1_used, rs2_used);
        end
        $finish;
    end
endmodule
