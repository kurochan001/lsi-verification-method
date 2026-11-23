`timescale 1ns/1ps
module mul_pipe_tb;
    parameter STAGES=3, MUTATION=0;
    reg clk=0, rst_n=1, vin=0;
    reg [7:0] a=0, b=0;
    wire vld;
    wire [15:0] out;
    mul_pipe #(.STAGES(STAGES), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .vin(vin), .a(a), .b(b), .vld(vld), .out(out));
    always #5 clk = ~clk;
    integer fd, n, checks=0;
    reg [63:0] v[0:5];
    reg recovering=0, vin_prev=0, seen_valid=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d vin=%b a=%h b=%h vld=%b exp_vld=%b out=%h exp=%h", checks, vin, a, b, vld, v[4][0], out, v[5][15:0]); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, mul_pipe_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5]);
            if (n != 6) $fatal(1, "bad row");
            rst_n = v[0][0]; vin = v[1][0]; a = v[2][7:0]; b = v[3][7:0];
            #1;
            if (vld !== v[4][0]) fail("MUL_TIME");
            if (out !== v[5][15:0]) fail("MUL_DATA");
            if (vin && (a == 0 || b == 0)) $display("COVER mul/zero");
            if (vin && a == 8'hff && b == 8'hff) $display("COVER mul/max");
            if (vin && (a == 1 || b == 1)) $display("COVER mul/one");
            if (vin && a[7:4] != 0) $display("COVER mul/hi-lane");
            if (vin && a[7:4] == 0 && a[3:0] != 0 && b != 0) $display("COVER mul/lo-only");
            if (vin && a == b) $display("COVER mul/same-operands");
            if (vin && vin_prev) $display("COVER mul/pipelined");
            if (vld) $display("COVER vld/active");
            if (!vld && seen_valid) $display("COVER vld/off");
            if (!rst_n) begin
                recovering = 1;
            end else if (vin) begin
                if (recovering) begin $display("COVER reset/recovery"); recovering = 0; end
            end
            if (vld) seen_valid = 1;
            vin_prev = vin;
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
