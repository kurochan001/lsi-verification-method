`timescale 1ns/1ps
// Rows: kind, three arguments, then what the always-on side must see when the row has settled:
// a_sum, a_idle_n, a_last, b_count, b_mode, pwr_a, pwr_b.
// The generated module pd_power_model injects X into the domains that are off and checks the
// isolation values, the power states and the order of the control signals on every clock.
module pd_tb;
    parameter MUTATION = 0, SETTLE = 2;
    localparam LIMIT = 200;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, req_a = 0, req_b = 0, op_valid = 0, op_sel = 0;
    reg [7:0] op_data = 0;
    wire op_ready, a_on, b_on, busy, pwr_a, pwr_b, a_idle_n;
    wire [7:0] a_sum, a_last, b_count;
    wire [3:0] b_mode;

    pd_top #(.MUTATION(MUTATION), .SETTLE(SETTLE)) dut (
        .clk(clk), .rst_n(rst_n), .req_a(req_a), .req_b(req_b),
        .op_valid(op_valid), .op_sel(op_sel), .op_data(op_data), .op_ready(op_ready),
        .a_on(a_on), .b_on(b_on), .busy(busy), .pwr_a(pwr_a), .pwr_b(pwr_b),
        .a_sum(a_sum), .a_idle_n(a_idle_n), .a_last(a_last), .b_count(b_count), .b_mode(b_mode));

    pd_power_model #(.SETTLE(SETTLE)) power_model (.clk(clk), .rst_n(rst_n));

    integer fd, n, checks, accepted, refused, power_requests, resets, guard;
    reg [31:0] v [0:10];
    reg [1:0] earlier;
    reg failed;
    string vectors, wave;

    task fail(input string label);
        begin
            if (!failed) begin
                failed = 1;
                $display("CHECK_FAIL %s", label);
                $fatal(1, "row=%0d time=%0t", checks, $time);
            end
        end
    endtask

    // Wait until the controller is idle in the state that the requests ask for.
    task settle;
        begin
            guard = 0;
            @(negedge clk);
            while ((busy !== 1'b0 || a_on !== req_a || b_on !== (req_a & req_b)) && guard < LIMIT) begin
                @(negedge clk);
                guard = guard + 1;
            end
            if (guard >= LIMIT) fail("PD_TIMEOUT");
        end
    endtask

    task request(input reg a, input reg b);
        begin
            earlier = {pwr_a, pwr_b};
            req_a = a;
            req_b = b;
            power_requests = power_requests + 1;
        end
    endtask

    task offer(input reg select, input reg [7:0] data, input reg expected);
        begin
            op_valid = 1;
            op_sel = select;
            op_data = data;
            #1;
            if (op_ready !== expected) fail("PD_ACCEPT");
            if (expected) accepted = accepted + 1; else refused = refused + 1;
            @(negedge clk);
            op_valid = 0;
        end
    endtask

    initial begin
        failed = 0; checks = 0; accepted = 0; refused = 0; power_requests = 0; resets = 0;
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, pd_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
            if (n != 11) $fatal(1, "bad row");
            case (v[0])
                0: begin  // global reset, with the requests that hold afterwards
                    if (pwr_a === 1'b1) $display("COVER reset/while-on");
                    if (pwr_a === 1'b0) $display("COVER reset/while-off");
                    rst_n = 0; op_valid = 0; req_a = v[1][0]; req_b = v[2][0];
                    repeat (2) @(negedge clk);
                    rst_n = 1;
                    resets = resets + 1;
                    settle;
                end
                1: begin  // one operand; v[3] says whether it is accepted
                    offer(v[1][0], v[2][7:0], v[3][0]);
                    if (!v[3][0]) $display("COVER flow/op-refused-off");
                end
                2: begin  // power request, then wait
                    request(v[1][0], v[2][0]);
                    settle;
                    if (earlier == 2'b11 && {pwr_a, pwr_b} == 2'b00) $display("COVER order/sleep-both");
                    if (earlier == 2'b00 && {pwr_a, pwr_b} == 2'b11) $display("COVER order/wake-both");
                    if (!v[1][0] && v[2][0]) $display("COVER order/b-request-without-a");
                end
                3: begin  // power-down request and an operand in the same cycle: the operand counts
                    request(v[1][0], v[2][0]);
                    offer(v[3][8], v[3][7:0], 1'b1);
                    settle;
                    $display("COVER flow/op-with-sleep");
                end
                4: begin  // an operand one cycle after the request, for the domain that is moving
                    request(v[1][0], v[2][0]);
                    @(negedge clk);
                    offer(v[3][8], v[3][7:0], 1'b0);
                    settle;
                    $display("COVER flow/op-refused-in-transition");
                end
                5: begin  // a request, and the opposite request v[3][5:2] cycles later
                    request(v[1][0], v[2][0]);
                    repeat (v[3][5:2]) @(negedge clk);
                    request(v[3][1], v[3][0]);
                    settle;
                    $display("COVER flow/wake-during-sleep");
                end
                default: $fatal(1, "unknown row kind");
            endcase
            repeat (2) @(negedge clk);
            if ({pwr_a, pwr_b} !== {v[9][0], v[10][0]}) fail("PD_POWER");
            if (a_sum !== v[4][7:0] || a_idle_n !== v[5][0] || a_last !== v[6][7:0] ||
                b_count !== v[7][7:0] || b_mode !== v[8][3:0]) fail("PD_DATA");
            checks = checks + 1;
        end
        $display("COUNT ops_accepted=%0d", accepted);
        $display("COUNT ops_refused=%0d", refused);
        $display("COUNT power_requests=%0d", power_requests);
        $display("COUNT resets=%0d", resets);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
