`timescale 1ns/1ps
// Simulation harness for the self-tests: one score vector per line, one result line each.
module topk_tb;
    parameter N=4, K=2, MUTATION=0;
    reg clk=0, rst_n=0, in_valid=0;
    reg [8*N-1:0] in_scores=0;
    wire out_valid;
    wire [8*K-1:0] out_scores;
    wire [$clog2(N)*K-1:0] out_index;
    topk_select #(.N(N), .K(K), .MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer fd, n;
    string vectors;
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "VECTORS required");
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        @(negedge clk); rst_n = 1;
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h\n", in_scores);
            if (n != 1) $fatal(1, "bad row");
            in_valid = 1;
            @(posedge clk); #1;
            if (!out_valid) $fatal(1, "missing result");
            $display("OUT %h %h", out_scores, out_index);
            @(negedge clk);
        end
        $finish;
    end
endmodule
