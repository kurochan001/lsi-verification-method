`timescale 1ns/1ps
// Fault campaign bench for the referenced lockstep monitor. It reads a workload and a fault list,
// runs the workload once per fault from reset, injects the fault through the generated
// injector.svh (hierarchical deposit for a one-cycle flip, force for a stuck bit) and writes one
// trace row per cycle. The reactive driver below is mirrored line by line in model.py (Workload).
module fault_campaign_tb;
    parameter MUTATION = 0, WAIT_LIMIT = 4, MAX_RETRY = 2, DRAIN = 2, CAP = 96;
    reg clk = 0, rst_n = 0, op_valid = 0, recover = 0;
    reg [1:0] op = 0;
    reg [7:0] operand = 0;
    wire [7:0] result;
    wire error, safe, done;
    wire [1:0] error_code;
    lockstep_monitor #(.MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .op_valid(op_valid), .op(op), .operand(operand),
        .fault_inject(1'b0), .recover(recover), .result(result),
        .error(error), .safe(safe), .error_code(error_code), .done(done));
    always #5 clk = ~clk;

`include "injector.svh"

    integer nops, ofd, ffd, tfd, n, g, a, o;
    integer ops_gap [0:63];
    reg [1:0] ops_op [0:63];
    reg [7:0] ops_arg [0:63];
    integer idx, gap, wait_cnt, retries, drain, alarms, status, cycle;
    integer fid, freg, fbit, fkind, fvalue, ftime, value_before, value_after;
    reg waiting, handled;
    string ops_path, faults_path, trace_path;

    // status: 0 running, 1 done, 2 stall (waited too long for done), 3 abandoned after alarms, 4 cycle cap
    task decide;
        begin
            op_valid = 0; op = 0; operand = 0; recover = 0; handled = 0;
            if (error === 1'b1) begin
                handled = 1;
                alarms = alarms + 1;
                if (waiting && ops_op[idx] == 2'd3) begin
                    idx = idx + 1; retries = 0; gap = idx < nops ? ops_gap[idx] : 0;
                end else if (waiting) begin
                    retries = retries + 1; gap = 0;
                end
                if (waiting && retries > MAX_RETRY) status = 3;
                else begin waiting = 0; recover = 1; end
            end
            if (!handled && waiting) begin
                if (done === 1'b1) begin
                    waiting = 0; idx = idx + 1; retries = 0; gap = idx < nops ? ops_gap[idx] : 0;
                end else begin
                    handled = 1;
                    wait_cnt = wait_cnt + 1;
                    if (wait_cnt >= WAIT_LIMIT) status = 2;
                    else begin op_valid = 1; op = ops_op[idx]; operand = ops_arg[idx]; end
                end
            end
            if (!handled) begin
                if (idx >= nops) begin
                    if (drain == 0) status = 1;
                    else drain = drain - 1;
                end else if (gap > 0) begin
                    gap = gap - 1;
                end else begin
                    waiting = 1; wait_cnt = 0;
                    op_valid = 1; op = ops_op[idx]; operand = ops_arg[idx];
                end
            end
        end
    endtask

    initial begin
        if (!$value$plusargs("OPS=%s", ops_path) || !$value$plusargs("FAULTS=%s", faults_path) ||
            !$value$plusargs("TRACE=%s", trace_path))
            $fatal(1, "OPS, FAULTS and TRACE are required");
        ofd = $fopen(ops_path, "r");
        if (!ofd) $fatal(1, "workload missing");
        nops = 0;
        while (!$feof(ofd)) begin
            n = $fscanf(ofd, "%d %d %d\n", g, o, a);
            if (n != 3) $fatal(1, "bad workload row");
            ops_gap[nops] = g; ops_op[nops] = o[1:0]; ops_arg[nops] = a[7:0];
            nops = nops + 1;
        end
        $fclose(ofd);
        ffd = $fopen(faults_path, "r");
        tfd = $fopen(trace_path, "w");
        if (!ffd || !tfd) $fatal(1, "fault list or trace cannot be opened");
        while (!$feof(ffd)) begin
            n = $fscanf(ffd, "%d %d %d %d %d %d\n", fid, freg, fbit, fkind, fvalue, ftime);
            if (n != 6) $fatal(1, "bad fault row");
            rst_n = 0; op_valid = 0; op = 0; operand = 0; recover = 0;
            @(negedge clk);
            @(negedge clk);
            rst_n = 1;
            idx = 0; gap = ops_gap[0]; waiting = 0; wait_cnt = 0; retries = 0; drain = DRAIN;
            status = 0; alarms = 0; cycle = 0;
            decide;
            while (status == 0) begin
                @(posedge clk);
                #1;
                if (fkind != 0 && cycle == ftime) begin
                    value_before = read_bit(freg, fbit);
                    if (fkind == 1) flip_bit(freg, fbit);
                    else force_bit(freg, fbit, fvalue);
                    value_after = read_bit(freg, fbit);
                    $fdisplay(tfd, "I %0d %0d %0d", fid, value_before, value_after);
                end
                @(negedge clk);
                $fdisplay(tfd, "R %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d", fid, cycle,
                          op_valid, op, operand, recover, result, done, error, safe, error_code);
                cycle = cycle + 1;
                decide;
                if (status == 0 && cycle >= CAP) status = 4;
            end
            $fdisplay(tfd, "E %0d %0d %0d %0d", fid, status, cycle, alarms);
            release_all;
        end
        $fclose(ffd);
        $fclose(tfd);
        $display("RESULT PASS faults");
        $finish;
    end
endmodule
