`timescale 1ns/1ps
// Each vector row holds one operation, one rounding mode, one value of a, and a list of
// values of b with the result and the flags expected for each. The design is combinational:
// the bench applies an operand pair, waits, and compares all bits. The tag word names the
// classes of stimulus in the row; they are credited when the whole row has been compared.
module fp_adder_tb;
    parameter EXP = 8, FRAC = 23, MUTATION = 0;
    localparam W = EXP + FRAC + 1, RW = W + 5, TAGS = 25;
    reg sub = 0;
    reg [2:0] rm = 0;
    reg [W-1:0] a = 0, b = 0;
    wire [W-1:0] result;
    wire [4:0] flags;
    fp_adder #(.EXP(EXP), .FRAC(FRAC), .MUTATION(MUTATION)) dut(.*);
    reg [4095:0] v[0:6];
    reg [RW-1:0] want;
    reg [TAGS-1:0] seen = 0;
    integer fd, n, i, count, checks = 0, additions = 0, subtractions = 0, invalid = 0, inexact = 0;
    string vectors, wave;
    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d sub=%b rm=%0d a=%h b=%h result=%h flags=%b want=%h", checks, sub, rm, a, b, result, flags, want);
        end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, sub, rm, a, b, result, flags);  // the ports; the internals would fill the file
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5], v[6]);
            if (n != 7) $fatal(1, "bad row");
            sub = v[0][0];
            rm = v[1][2:0];
            a = v[2][W-1:0];
            count = v[3][15:0];
            for (i = 0; i < count; i = i + 1) begin
                b = v[4][i*W +: W];
                want = v[5][i*RW +: RW];
                #1;
                if (^{result, flags} === 1'bx) fail("FP_X");
                if (result !== want[RW-1:5]) fail("FP_VALUE");
                if (flags !== want[4:0]) fail("FP_FLAGS");
                if (sub) subtractions = subtractions + 1; else additions = additions + 1;
                if (flags[4]) invalid = invalid + 1;
                if (flags[0]) inexact = inexact + 1;
            end
            seen = seen | v[6][TAGS-1:0];
            checks = checks + 1;
        end
        if (seen[0]) $display("COVER operand/zero");
        if (seen[1]) $display("COVER operand/subnormal");
        if (seen[2]) $display("COVER operand/infinity");
        if (seen[3]) $display("COVER operand/quiet-nan");
        if (seen[4]) $display("COVER operand/signaling-nan");
        if (seen[5]) $display("COVER result/positive-zero");
        if (seen[6]) $display("COVER result/negative-zero");
        if (seen[7]) $display("COVER result/subnormal");
        if (seen[8]) $display("COVER result/overflow-infinity");
        if (seen[9]) $display("COVER result/overflow-largest-finite");
        if (seen[10]) $display("COVER result/invalid-infinities");
        if (seen[11]) $display("COVER round/exact");
        if (seen[12]) $display("COVER round/tie");
        if (seen[13]) $display("COVER round/away");
        if (seen[14]) $display("COVER round/toward");
        if (seen[15]) $display("COVER round/carry-into-exponent");
        if (seen[16]) $display("COVER align/cancellation");
        if (seen[17]) $display("COVER align/far");
        if (seen[18]) $display("COVER operation/add");
        if (seen[19]) $display("COVER operation/subtract");
        if (seen[20]) $display("COVER mode/rne");
        if (seen[21]) $display("COVER mode/rtz");
        if (seen[22]) $display("COVER mode/rdn");
        if (seen[23]) $display("COVER mode/rup");
        if (seen[24]) $display("COVER mode/rmm");
        $display("COUNT additions=%0d", additions);
        $display("COUNT subtractions=%0d", subtractions);
        $display("COUNT invalid=%0d", invalid);
        $display("COUNT inexact=%0d", inexact);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
