`timescale 1ps/1ps
// One bench for three clock circuits. Inputs change only at times given by the vector file,
// never on a clock edge. The checks read the real edge times of the outputs.
module clock_gating_tb;
    parameter integer MUTATION = 0, PERIOD_A = 10000, PERIOD_B = 14000, DIV = 3;
    localparam integer HALF_A = PERIOD_A / 2, HALF_B = PERIOD_B / 2;
    localparam integer MIN_SWITCH = HALF_A < HALF_B ? HALF_A : HALF_B;

    // Free-running clock of the gate and the divider.
    reg clk = 0;
    always #(HALF_A) clk = ~clk;
    // Clocks of the switch. Each can be stopped at either level and resumes on its own grid.
    reg sw_a = 0, sw_b = 0, run_a = 1, run_b = 1;
    always #(HALF_A) if (run_a) sw_a = ~sw_a;
    always #(HALF_B) if (run_b) sw_b = ~sw_b;

    reg enable = 0, sel = 0, sw_rst_n = 0, div_rst_n = 0;
    wire gclk, sw_out, active_a, active_b, div_out;
    clock_gate #(.MUTATION(MUTATION)) gate(.clk(clk), .enable(enable), .gclk(gclk));
    clock_switch #(.MUTATION(MUTATION)) switch(.clk_a(sw_a), .clk_b(sw_b), .arst_n(sw_rst_n), .sel(sel),
                                               .clk_out(sw_out), .active_a(active_a), .active_b(active_b));
    odd_divider #(.DIV(DIV), .MUTATION(MUTATION)) divider(.clk(clk), .arst_n(div_rst_n), .clk_out(div_out));

    integer fd, trace_fd, fields, checks = 0;
    reg [31:0] delay, signal, value;
    string vectors, wave, edges;
    reg armed = 0;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "time_ps=%0d row=%0d gclk=%b sw_out=%b active=%b%b div_out=%b", $time, checks,
                   gclk, sw_out, active_b, active_a, div_out);
        end
    endtask

    // ---- clock gate: every output pulse is a whole clock pulse ----
    integer gate_rises = 0, gate_checked = 0;
    longint gate_rise_at = 0, gate_fall_at = 0;
    reg gate_fell = 0;
    reg gate_pass = 0, gate_held_off = 0, gate_change_high = 0, gate_change_low = 0;
    always @(gclk) begin
        if (armed) begin
            $fdisplay(trace_fd, "%0d,gclk,%b", $time, gclk);
            if (gclk === 1'b1) begin
                if (enable !== 1'b1) fail("CG_OFF_EDGE");
                if (gate_fell && $time - gate_fall_at < HALF_A) fail("CG_SHORT_LOW");
                gate_rise_at = $time;
                gate_rises = gate_rises + 1;
            end else if (gclk === 1'b0) begin
                if ($time - gate_rise_at < HALF_A) fail("CG_SHORT_HIGH");
                gate_fall_at = $time;
                gate_fell = 1;
            end else
                fail("CK_X");
        end
    end

    // ---- clock switch: no pulse shorter than the shorter clock allows, never two clocks at once ----
    integer window_rises = 0, windows = 0, releases = 0;
    longint switch_rise_at = 0, switch_fall_at = 0;
    reg switch_rose = 0, switch_fell = 0;
    reg [1:0] last_active = 0;
    reg a_to_b = 0, b_to_a = 0, select_high = 0, target_stopped = 0, current_stopped = 0, recovered = 0, release_on_b = 0;
    always @(sw_out) begin
        if (armed) begin
            $fdisplay(trace_fd, "%0d,sw_out,%b", $time, sw_out);
            if (sw_rst_n !== 1'b1) begin
                // An edge made by the reset itself, or while reset: measuring starts again afterwards.
                switch_rose = 0;
                switch_fell = 0;
            end else if (sw_out === 1'b1) begin
                if (switch_fell && $time - switch_fall_at < MIN_SWITCH) fail("CS_SHORT_LOW");
                switch_rise_at = $time;
                switch_rose = 1;
                window_rises = window_rises + 1;
            end else if (sw_out === 1'b0) begin
                if (switch_rose && $time - switch_rise_at < MIN_SWITCH) fail("CS_SHORT_HIGH");
                switch_fall_at = $time;
                switch_fell = 1;
            end else
                fail("CK_X");
        end
    end
    always @(active_a or active_b) begin
        if (armed && active_a === 1'b1 && active_b === 1'b1) fail("CS_OVERLAP");
    end

    // ---- odd divider: period of DIV input periods, high and low of the same length ----
    integer divider_rises = 0, divider_total = 0, divider_releases = 0, duty_measured = 0;
    longint divider_rise_at = 0, divider_fall_at = 0;
    reg divider_rose = 0, divider_fell = 0, divider_restart = 0;
    always @(div_out) begin
        if (armed && div_rst_n === 1'b1) begin
            $fdisplay(trace_fd, "%0d,div_out,%b", $time, div_out);
            if (div_out === 1'b1) begin
                if (divider_fell) begin
                    if ($time - divider_rise_at != DIV * PERIOD_A) fail("DIV_PERIOD");
                    if ($time - divider_fall_at != DIV * HALF_A) fail("DIV_DUTY");
                    duty_measured = duty_measured + 1;
                end
                divider_rise_at = $time;
                divider_rose = 1;
                divider_rises = divider_rises + 1;
                divider_total = divider_total + 1;
            end else if (div_out === 1'b0) begin
                if (divider_rose) begin
                    if ($time - divider_rise_at != DIV * HALF_A) fail("DIV_DUTY");
                    divider_fall_at = $time;
                    divider_fell = 1;
                end
            end else
                fail("CK_X");
        end
    end

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "missing run arguments");
        $dumpfile(wave);
        $dumpvars(0, clock_gating_tb);
        fd = $fopen(vectors, "r");
        // Next to the waveform, not in the directory the simulator was started from.
        edges = $sformatf("%s.edges.csv", wave);
        trace_fd = $fopen(edges, "w");
        if (!fd || !trace_fd) $fatal(1, "cannot open run files");
        $fdisplay(trace_fd, "time_ps,signal,value");
        while (!$feof(fd)) begin
            fields = $fscanf(fd, "%h %h %h\n", delay, signal, value);
            if (fields != 3 || ^{delay, signal, value} === 1'bx) $fatal(1, "bad vector");
            #(delay);
            armed = 1;
            case (signal)
                0: begin
                    if (clk) gate_change_high = 1; else gate_change_low = 1;
                    enable = value[0];
                end
                1: begin
                    if (sw_out === 1'b1) select_high = 1;
                    sel = value[0];
                end
                2: run_a = value[0];
                3: run_b = value[0];
                4: begin
                    switch_rose = 0;
                    switch_fell = 0;
                    if (value[0]) releases = releases + 1;
                    sw_rst_n = value[0];
                end
                5: begin
                    if (!value[0]) begin
                        divider_rose = 0;
                        divider_fell = 0;
                        divider_rises = 0;
                    end else
                        divider_releases = divider_releases + 1;
                    div_rst_n = value[0];
                end
                8: begin
                    if (gclk === 1'bx) fail("CK_X");
                    if (gate_rises != value) fail("CG_EDGES");
                    if (gate_rises > gate_checked) gate_pass = 1;
                    if (gate_rises == gate_checked && !enable) gate_held_off = 1;
                    gate_checked = gate_rises;
                end
                9: begin
                    if (^{sw_out, active_a, active_b} === 1'bx) fail("CK_X");
                    if ({active_b, active_a} !== value[1:0]) fail("CS_ACTIVE");
                    if (value[1:0] == 2'b00) target_stopped = 1;
                    else begin
                        if (value[1] != sel) current_stopped = 1;
                        else begin
                            if (last_active == 2'b01 && value[1:0] == 2'b10) a_to_b = 1;
                            if (last_active == 2'b10 && value[1:0] == 2'b01) b_to_a = 1;
                            if (releases >= 2 && current_stopped) recovered = 1;
                        end
                        last_active = value[1:0];
                    end
                end
                10: window_rises = 0;
                11: begin
                    if (window_rises != value) fail("CS_EDGES");
                    windows = windows + 1;
                end
                12: begin
                    if (div_out === 1'bx) fail("CK_X");
                    if (divider_rises != value) fail("DIV_EDGES");
                    if (divider_releases >= 2 && value >= 2) divider_restart = 1;
                end
                13: begin
                    // Shortly after a reset release: the reset state must not enable a clock by itself.
                    if (^{sw_out, active_a, active_b} === 1'bx) fail("CK_X");
                    if ({active_b, active_a} !== value[1:0]) fail("CS_ACTIVE");
                    if (sel === 1'b1) release_on_b = 1;
                end
                default: $fatal(1, "unknown signal");
            endcase
            checks = checks + 1;
        end
        if (gate_pass) $display("COVER gate/pass");
        if (gate_held_off) $display("COVER gate/held-off");
        if (gate_change_high) $display("COVER gate/change-while-high");
        if (gate_change_low) $display("COVER gate/change-while-low");
        if (a_to_b) $display("COVER switch/a-to-b");
        if (b_to_a) $display("COVER switch/b-to-a");
        if (select_high) $display("COVER switch/select-while-high");
        if (target_stopped) $display("COVER switch/target-stopped");
        if (current_stopped) $display("COVER switch/current-stopped");
        if (recovered) $display("COVER switch/reset-recovery");
        if (release_on_b) $display("COVER switch/release-on-b");
        if (duty_measured >= 2) $display("COVER divider/duty");
        if (divider_restart) $display("COVER divider/restart");
        $fclose(fd);
        $fclose(trace_fd);
        $display("COUNT steps=%0d", checks);
        $display("COUNT gate_pulses=%0d", gate_rises);
        $display("COUNT switch_windows=%0d", windows);
        $display("COUNT divider_pulses=%0d", divider_total);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
