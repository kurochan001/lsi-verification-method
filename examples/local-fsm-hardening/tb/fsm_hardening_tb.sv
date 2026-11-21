`timescale 1ns/1ps
// Vector-driven test bench. Each row holds the inputs of one clock edge, the bits to flip at
// that edge, how to check the outputs after it, and the outputs of the lock without faults.
//   mode 0 exact: the outputs equal those of the lock without faults
//   mode 1 first: the first flip since reset; grant only where the lock without faults grants
//   mode 2 after: a later row before reset; from the first of these rows the lock must be in
//                 ERROR and stay there; grant only where the lock without faults grants
//   mode 3 again: a further flip while in ERROR; grant only where the lock without faults grants
// A mismatch in an exact row stops at once. The outcome of each first flip is collected until
// the reset that closes it, so that every flip of the plan is judged; the worst outcome over the
// whole run decides: a grant that the lock without faults would not give, then a flip that never
// reached ERROR, then a lock that left ERROR before reset.
module fsm_hardening_tb;
    parameter MAX_TRIES = 3, MUTATION = 0;
    localparam FW = 10;
    localparam [FW-1:0] ALL = {FW{1'b1}};

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, start = 0, key_ok = 0, relock = 0;
    reg [FW-1:0] fault_xor = 0;
    wire grant, busy, lockout, alarm;
    wire [1:0] fails;
    hardened_lock #(.HARDENED(1), .MAX_TRIES(MAX_TRIES), .MUTATION(MUTATION)) dut(.*);

    reg [31:0] vr, vs, vk, vl, vf, vm, eg, eb, eo, ea, ef;
    reg pg = 0, pb = 0, po = 0;          // outputs of the lock without faults before the edge
    reg [1:0] pf = 0;
    reg open = 0, escalate = 0, detected = 0, escape = 0, waiting = 0, injected = 0;
    reg [FW-1:0] seen_locked = 0, seen_check = 0, seen_open = 0, seen_lockout = 0, seen_error = 0;
    integer fd, rc, checks = 0, flips = 0, again = 0, escalated = 0, undetected = 0, escaped = 0;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d mode=%0d grant=%b busy=%b lockout=%b alarm=%b fails=%0d expected=%b%b%b%b%0d",
                   checks, vm, grant, busy, lockout, alarm, fails, eg[0], eb[0], eo[0], ea[0], ef[1:0]);
        end
    endtask

    task close_flip;   // judge the flip opened by the last first row
        begin
            if (open) begin
                if (escalate) escalated = escalated + 1;
                else if (!detected) undetected = undetected + 1;
                else if (escape) escaped = escaped + 1;
                open = 0;
            end
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "VECTORS required");
        if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, fsm_hardening_tb); end
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        repeat (2) @(negedge clk);   // known reset before the first row
        while (!$feof(fd)) begin
            rc = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n", vr, vs, vk, vl, vf, vm, eg, eb, eo, ea, ef);
            if (rc != 11) $fatal(1, "malformed vector");
            if (vm > 3 || (vm == 1 || vm == 3) != (vf != 0) || (!vr[0] && vf != 0)) $fatal(1, "inconsistent row");
            rst_n = vr[0]; start = vs[0]; key_ok = vk[0]; relock = vl[0]; fault_xor = vf[FW-1:0];
            @(posedge clk); #1;
            if (^{grant, busy, lockout, alarm, fails} === 1'bx) fail("FSM_UNKNOWN");
            if (vm == 0) begin
                close_flip;
                if (alarm !== ea[0]) fail("FSM_ALARM");
                if ({grant, busy, lockout} !== {eg[0], eb[0], eo[0]}) fail("FSM_STATE");
                if (fails !== ef[1:0]) fail("FSM_FAILS");
                if (!rst_n) begin
                    if (pg) $display("COVER fsm/reset-from-open");
                    if (po) $display("COVER fsm/reset-from-lockout");
                end else begin
                    if (!pg && !pb && !po && start && busy) $display("COVER fsm/check-from-locked");
                    if (!pg && !pb && !po && key_ok && !start && !busy && !grant) $display("COVER fsm/key-without-start");
                    if (pb && key_ok && grant) $display("COVER fsm/open-on-key");
                    if (pb && key_ok && grant && pf != 0 && fails == 0) $display("COVER fsm/success-clears-fails");
                    if (pb && !key_ok && !lockout && !busy && fails != 0) $display("COVER fsm/retry-after-fail");
                    if (pb && lockout) $display("COVER fsm/lockout-at-limit");
                    if (po && lockout && start && key_ok && relock) $display("COVER fsm/lockout-holds");
                    if (pg && relock && !grant && !busy) $display("COVER fsm/relock");
                    if (injected && grant) $display("COVER fault/reset-recovers");
                end
            end else if (vm == 1) begin
                close_flip;
                open = 1; escalate = grant && !eg[0]; detected = 0; escape = 0; waiting = 1; injected = 1;
                flips = flips + 1;
                if (vf[FW-1:4] != 0) begin
                    if (eg[0]) $display("COVER fault/state-open");
                    else if (eb[0]) $display("COVER fault/state-check");
                    else if (eo[0]) $display("COVER fault/state-lockout");
                    else $display("COVER fault/state-locked");
                end
                if (vf[3:2] != 0) $display("COVER fault/counter-true");
                if (vf[1:0] != 0) $display("COVER fault/counter-complement");
                if ({eg[0], eb[0], eo[0]} != {pg, pb, po}) $display("COVER fault/at-transition");
                if (ef[1:0] != pf) $display("COVER fault/at-counter-update");
                if (eg[0] && !grant) $display("COVER fault/grant-removed");
                if (eg[0]) seen_open = seen_open | vf[FW-1:0];
                else if (eb[0]) seen_check = seen_check | vf[FW-1:0];
                else if (eo[0]) seen_lockout = seen_lockout | vf[FW-1:0];
                else seen_locked = seen_locked | vf[FW-1:0];
            end else if (vm == 2) begin
                if (!open) $fatal(1, "after row without a flip");
                if (grant && !eg[0]) escalate = 1;
                if (waiting) begin
                    detected = alarm;
                    waiting = 0;
                end else if (detected && !alarm) escape = 1;
                if (alarm && (start || key_ok || relock)) $display("COVER fault/error-holds-inputs");
            end else begin
                if (!open) $fatal(1, "second flip without a first");
                if (grant && !eg[0]) escalate = 1;
                again = again + 1;
                if (detected && vf[FW-1:4] != 0) $display("COVER fault/state-error");
                if (detected) seen_error = seen_error | vf[FW-1:0];
            end
            if ({seen_locked, seen_check, seen_open, seen_lockout, seen_error} == {5{ALL}})
                $display("COVER fault/every-bit-every-state");
            pg = eg[0]; pb = eb[0]; po = eo[0]; pf = ef[1:0];
            checks = checks + 1;
            @(negedge clk);
        end
        $fclose(fd);
        close_flip;
        $display("FLIPS first=%0d again=%0d escalated=%0d undetected=%0d escaped=%0d",
                 flips, again, escalated, undetected, escaped);
        if (escalated != 0) fail("FSM_ESCALATE");
        if (undetected != 0) fail("FSM_UNDETECTED");
        if (escaped != 0) fail("FSM_ESCAPE");
        $display("COUNT flips=%0d", flips);
        $display("COUNT again=%0d", again);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
