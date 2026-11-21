`timescale 1ns/1ps
// Vector-driven stream bench. The rows are read first; a driver walks the configuration and
// pixel rows in order and a monitor walks the expected rows in order, both in the same clock loop.
//   kind 0 configuration: in_w in_h out_w out_h flags   (flags bit 0: refused, bit 1: mid-frame)
//   kind 1 pixel:         value gap first before        (idle cycles before it is offered; the first
//                         pixel of a frame carries the number of outputs of all earlier frames)
//   kind 2 expected:      value last stall              (cycles with out_ready low once it is shown)
// Every row counts as one check when it is done: a configuration when applied (a refused one when
// cfg_error and in_ready have been checked with the scaler idle), a pixel when accepted, an
// expected pixel when it is taken and matches. Bit i of the tags names a goal (TAGS in run.py).
module image_scaler_tb;
    parameter MAX_W = 12, MAX_H = 12, MUTATION = 0;
    localparam N = 16384;
    localparam CONFIG = 0, PIXEL = 1, EXPECT = 2;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, in_valid = 0, out_ready = 1;
    reg [7:0] cfg_in_w = 8'd1, cfg_in_h = 8'd1, cfg_out_w = 8'd1, cfg_out_h = 8'd1, in_pixel = 8'd0;
    wire in_ready, out_valid, out_last, cfg_error, busy;
    wire [7:0] out_pixel;
    image_scaler #(.MAX_W(MAX_W), .MAX_H(MAX_H), .MUTATION(MUTATION)) dut(.*);

    reg [31:0] rk [0:N-1];
    reg [31:0] ra [0:N-1];
    reg [31:0] rb [0:N-1];
    reg [31:0] rc [0:N-1];
    reg [31:0] rd [0:N-1];
    reg [31:0] re [0:N-1];
    reg [31:0] rt [0:N-1];
    reg [31:0] v0, v1, v2, v3, v4, v5, v6;
    reg [8:0] held_payload = 9'd0;
    reg held = 0, progressed = 0;
    integer fd, scan, n = 0, checks = 0, di, mi, gap_left, stall_left, idle = 0, wait_refused = 0;
    integer frames = 0, outputs = 0, k;
    string vectors, wave;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "checks=%0d driver_row=%0d monitor_row=%0d out_pixel=%h out_last=%b", checks, di, mi, out_pixel, out_last);
        end
    endtask

    function string goal(input integer bit_index);
        case (bit_index)
            0: goal = "map/tie-column";            1: goal = "map/tie-row";
            2: goal = "map/repeat-column";         3: goal = "map/skip-column";
            4: goal = "map/repeat-row";            5: goal = "map/skip-row";
            6: goal = "edge/right";                7: goal = "edge/bottom";
            8: goal = "phase/period-return";       9: goal = "frame/last";
            10: goal = "size/max";                 11: goal = "size/one";
            12: goal = "ratio/down";               13: goal = "ratio/up";
            14: goal = "ratio/identity";           15: goal = "config/size-change";
            16: goal = "config/midframe-ignored";  17: goal = "config/error-in-w-zero";
            18: goal = "config/error-in-w-over";   19: goal = "config/error-in-h-zero";
            20: goal = "config/error-in-h-over";   21: goal = "config/error-out-w-zero";
            22: goal = "config/error-out-w-over";  23: goal = "config/error-out-h-zero";
            24: goal = "config/error-out-h-over";
            default: goal = "";
        endcase
    endfunction

    integer nxd [0:N];                 // first driver row at or after i
    integer nxm [0:N];                 // first expected row at or after i
    function integer next_driver(input integer from);
        next_driver = from >= n ? n : nxd[from];
    endfunction
    function integer next_monitor(input integer from);
        next_monitor = from >= n ? n : nxm[from];
    endfunction

    task done(input integer row);
        begin
            for (k = 0; k < 25; k = k + 1)
                if (rt[row][k]) $display("COVER %s", goal(k));
            checks = checks + 1;
            progressed = 1;
        end
    endtask

    task advance_driver;
        begin
            di = next_driver(di + 1);
            gap_left = (di < n && rk[di] == PIXEL) ? rb[di] : 0;
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors)) $fatal(1, "VECTORS required");
        if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, image_scaler_tb); end
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "cannot open vectors");
        while (!$feof(fd)) begin
            scan = $fscanf(fd, "%h %h %h %h %h %h %h\n", v0, v1, v2, v3, v4, v5, v6);
            if (scan != 7 || n >= N || v0 > EXPECT || v6 >= 32'h2000000) $fatal(1, "malformed vector");
            rk[n] = v0; ra[n] = v1; rb[n] = v2; rc[n] = v3; rd[n] = v4; re[n] = v5; rt[n] = v6;
            n = n + 1;
        end
        $fclose(fd);
        nxd[n] = n; nxm[n] = n;
        for (k = n - 1; k >= 0; k = k - 1) begin
            nxd[k] = rk[k] != EXPECT ? k : nxd[k + 1];
            nxm[k] = rk[k] == EXPECT ? k : nxm[k + 1];
        end
        di = next_driver(0);
        mi = next_monitor(0);
        gap_left = (di < n && rk[di] == PIXEL) ? rb[di] : 0;
        stall_left = mi < n ? rc[mi] : 0;
        repeat (3) @(negedge clk);
        rst_n = 1;
        while (checks < n) begin
            @(negedge clk);
            progressed = 0;
            in_valid = 0;
            if (di < n && rk[di] == CONFIG) begin
                cfg_in_w = ra[di][7:0]; cfg_in_h = rb[di][7:0]; cfg_out_w = rc[di][7:0]; cfg_out_h = rd[di][7:0];
                if (!re[di][0]) begin               // accepted sizes take effect at once, mid-frame too
                    done(di);
                    advance_driver;
                end
            end
            if (di < n && rk[di] == PIXEL) begin
                if (gap_left > 0) begin
                    gap_left = gap_left - 1;
                    $display("COVER stream/in-gap");
                end else begin
                    in_valid = 1;
                    in_pixel = ra[di][7:0];
                end
            end
            out_ready = !(out_valid && stall_left > 0);
            #1;
            if ((^{in_ready, out_valid, cfg_error, busy}) === 1'bx) fail("SCALE_UNKNOWN");
            if (held && (out_valid !== 1'b1 || {out_last, out_pixel} !== held_payload)) fail("SCALE_HOLD");
            if (di < n && rk[di] == CONFIG && re[di][0]) begin   // refused sizes: checked with the scaler idle
                if (mi > di && busy === 1'b0) begin
                    wait_refused = wait_refused + 1;
                    if (wait_refused >= 2) begin
                        if (cfg_error !== 1'b1 || in_ready !== 1'b0) fail("SCALE_CONFIG");
                        wait_refused = 0;
                        done(di);
                        advance_driver;
                    end
                end
            end
            if (in_valid && !in_ready) $display("COVER stream/in-wait");
            if (out_valid && !out_ready) begin
                $display("COVER stream/out-stall");
                stall_left = stall_left - 1;
            end
            if (out_valid && out_ready) begin
                if (mi >= n) fail("SCALE_EXTRA");
                if (out_pixel !== ra[mi][7:0]) fail("SCALE_DATA");
                if (out_last !== rb[mi][0]) fail("SCALE_LAST");
                outputs = outputs + 1;
                if (out_last) frames = frames + 1;
                done(mi);
                mi = next_monitor(mi + 1);
                stall_left = mi < n ? rc[mi] : 0;
            end
            held = out_valid && !out_ready;
            held_payload = {out_last, out_pixel};
            if (in_valid && in_ready) begin
                // A new frame may start only when every output of the earlier frames has been made:
                // at most the last one can still wait in the output register.
                if (rc[di][0] && outputs + 1 < rd[di]) fail("SCALE_FRAME");
                done(di);
                advance_driver;
            end
            idle = progressed ? 0 : idle + 1;
            if (idle > 64 + 4 * MAX_W * MAX_H) fail("SCALE_TIMEOUT");
        end
        repeat (4 * MAX_W * MAX_H + 16) begin                // nothing more may come out
            @(negedge clk);
            in_valid = 0;
            out_ready = 1;
            #1;
            if (out_valid) fail("SCALE_EXTRA");
        end
        $display("COUNT frames=%0d", frames);
        $display("COUNT outputs=%0d", outputs);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
