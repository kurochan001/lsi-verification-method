`timescale 1ns/1ps
// Drives the three netlists with the same vectors, checks the register value in every cycle
// and writes the activity file that OpenSTA reads.
module power_tb;
    localparam real HALF = 5.0;  // 10 ns period: the period of the clock in power.tcl
    reg clk = 1'b0, en = 1'b0;
    wire bypass = 1'b1;          // the test bypass of the clock gate, never released
    reg [7:0] d = 8'h00;
    wire [7:0] q_plain, q_gated, q_stuck;
    integer fd, n, checks = 0, loads = 0;
    reg [7:0] v_en, v_d, v_q;
    string vectors, wave;

    bank_plain plain(.clk(clk), .en(en), .d(d), .q(q_plain));
    bank_gated gated(.clk(clk), .en(en), .d(d), .q(q_gated));
    bank_stuck stuck(.clk(clk), .en(en), .bypass(bypass), .d(d), .q(q_stuck));

    always #(HALF) clk = ~clk;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d", checks);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        $dumpfile(wave);
        $dumpvars(0, power_tb.plain, power_tb.gated, power_tb.stuck);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h\n", v_en, v_d, v_q);
            if (n != 3) $fatal(1, "bad row");
            @(negedge clk);
            // The value loaded, or held, at the edge before this one.
            if (checks > 0) begin
                if (^{q_plain, q_gated, q_stuck} === 1'bx) fail("POWER_X");
                if (q_plain !== q_gated || q_plain !== q_stuck) fail("POWER_EQUAL");
            end
            en = v_en[0];
            d = v_d;
            if (en) loads = loads + 1;
            @(posedge clk);
            #1;
            if (q_plain !== v_q) fail("POWER_VALUE");
            checks = checks + 1;
        end
        @(negedge clk);
        $display("COUNT loads=%0d", loads);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
