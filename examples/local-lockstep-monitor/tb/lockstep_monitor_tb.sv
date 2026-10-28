`timescale 1ns/1ps
module lockstep_monitor_tb;
    parameter FAULT_BIT=0, MUTATION=0;
    reg clk=0, rst_n=1, op_valid=0, fault_inject=0, recover=0;
    reg [1:0] op=0;
    reg [7:0] operand=0;
    wire [7:0] result;
    wire error, safe, done;
    wire [1:0] error_code;
    lockstep_monitor #(.FAULT_BIT(FAULT_BIT), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .op_valid(op_valid), .op(op), .operand(operand),
        .fault_inject(fault_inject), .recover(recover), .result(result),
        .error(error), .safe(safe), .error_code(error_code), .done(done));
    always #5 clk = ~clk;
    integer fd, n, checks=0;
    reg [63:0] v[0:10];
    reg recovering=0, recovered_once=0;
    reg [1:0] prev_op=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d op=%0d result=%h error=%b safe=%b code=%0d done=%b", checks, op, result, error, safe, error_code, done); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, lockstep_monitor_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
            if (n != 11) $fatal(1, "bad row");
            rst_n = v[0][0]; op_valid = v[1][0]; op = v[2][1:0]; operand = v[3][7:0];
            fault_inject = v[4][0]; recover = v[5][0];
            #1;
            if (prev_op == 2'b11 && error_code !== v[9][1:0]) fail("LOCKSTEP_ILLEGAL");
            if (error !== v[7][0]) fail("LOCKSTEP_COMPARE");
            if (safe !== v[8][0]) fail("LOCKSTEP_CONTAIN");
            if (result !== v[6][7:0]) fail("LOCKSTEP_RESULT");
            if (done !== v[10][0]) fail("LOCKSTEP_RESULT");
            if (!rst_n) begin
                recovering = 1; recovered_once = 0;
            end else begin
                if (op_valid && !safe) begin
                    if (op == 2'b00) $display("COVER op/add");
                    if (op == 2'b01) $display("COVER op/xor");
                    if (op == 2'b10) $display("COVER op/load");
                end
                if (error && error_code == 1) $display("COVER fault/detected");
                if (error && error_code == 2) $display("COVER illegal/detected");
                if (error && error_code != 0) $display("COVER error/code");
                if (safe && result == 0) begin
                    $display("COVER fault/contained");
                    $display("COVER output/frozen");
                end
                if (recover && error) begin
                    $display("COVER fault/recovered"); recovered_once = 1;
                end
                if (recovered_once && error && error_code == 1) $display("COVER fault/persistent");
                if (done && !error) begin
                    $display("COVER normal/no-false-error");
                    if (recovering) begin $display("COVER reset/recovery"); recovering = 0; end
                end
            end
            prev_op = op;
            checks = checks + 1;
            @(posedge clk); #1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
