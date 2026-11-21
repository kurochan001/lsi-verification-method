`timescale 1ns/1ps
// One boot per run. The rows load the boot ROM, the boot flash and the OTP values, schedule
// interrupts and resets, and give the expected outcome. Every clock (on the falling edge) the
// bench checks what must never happen whatever the circuit thinks: the verdict, debug
// enabled without a PASS that was expected, key words returned to code that may not have
// them, image instructions outside the verified payload, and grants that survive a reset.
// At the end it compares where the core stopped, the RAM words the programs wrote and the
// final verdict with the expected values.
module secure_boot_tb;
    parameter MUTATION = 0, IMG_MAX = 112, WAIT = 0;
    localparam [31:0] EBREAK = 32'h00100073;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, irq_req = 0;
    reg [31:0] rom [0:1023];
    reg [31:0] flash [0:255];
    reg [255:0] otp_digest = 0;
    reg [127:0] otp_key = 0;
    reg [7:0] otp_min_version = 0;
    reg [1:0] lifecycle = 0;
    wire [31:0] fetch_addr;
    wire [7:0] flash_addr;
    wire [31:0] fetch_data = fetch_addr < 32'h1000 ? rom[fetch_addr[11:2]] :
                             fetch_addr < 32'h1400 ? flash[fetch_addr[9:2]] : 32'h00000013;
    wire [31:0] flash_data = flash[flash_addr];
    wire debug_enable, bus_error, ret_valid, halted;
    wire [7:0] boot_status;
    wire [31:0] ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data;
    wire [4:0] ret_rd;
    wire [1:0] ret_mem;

    secure_boot_soc #(.IMG_MAX(IMG_MAX), .WAIT(WAIT), .MUTATION(MUTATION)) dut (.*);

    // ---- rows ----
    integer fd, n, rows = 0, i;
    reg [31:0] f0, f1, f2, f3;
    string vectors, wave;
    reg [7:0] exp_status;
    reg [31:0] exp_halt, exec_lo, exec_hi;
    reg may_exec, exp_debug;
    integer max_cycles = 4000;
    reg [31:0] exp_ram [0:6];
    integer ev_ref [0:15], ev_delay [0:15], ev_kind [0:15], events = 0;
    reg ev_fired [0:15];

    // ---- observation ----
    integer cycle = 0, released_at = -1, t_start = -1, t_image = -1, reset_left = 0;
    integer starts = 0, irqs = 0, bus_errors = 0, settle = 0;
    reg verdict_seen = 0, started = 0, prev_busy = 0, debug_seen = 0, finished = 0;
    reg [7:0] seen_status;
    reg [31:0] last_ebreak = 32'hffffffff;
    reg [31:0] shadow [0:6];
    reg [6:0] shadow_written = 0;
    // Coverage seen while the run passed every check.
    reg c_blocked_check = 0, c_blocked_fail = 0, c_tail = 0, c_header = 0, c_key_granted = 0, c_key_denied = 0;
    reg c_lc_secure = 0, c_lc_refused = 0, c_forge = 0, c_restart = 0, c_irq_check = 0;
    reg c_reset_check = 0, c_reset_image = 0;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "cycle=%0d", cycle);
        end
    endtask

    wire key_load = ret_mem == 2'd1 && ret_mem_addr >= 32'h40000010 && ret_mem_addr <= 32'h4000001c;
    wire in_flash = ret_pc >= 32'h00001000 && ret_pc < 32'h00001400;
    wire allows = lifecycle == 2'd0 || lifecycle == 2'd1;
    reg [31:0] key_word;
    always @* case (ret_mem_addr[3:2])
        2'd0: key_word = otp_key[127:96];
        2'd1: key_word = otp_key[95:64];
        2'd2: key_word = otp_key[63:32];
        default: key_word = otp_key[31:0];
    endcase

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "missing run arguments");
        $dumpfile(wave);
        $dumpvars(1, secure_boot_tb);
        for (i = 0; i < 1024; i = i + 1) rom[i] = EBREAK;
        for (i = 0; i < 256; i = i + 1) flash[i] = 32'd0;
        for (i = 0; i < 7; i = i + 1) exp_ram[i] = 32'd0;
        for (i = 0; i < 16; i = i + 1) ev_fired[i] = 0;
        fd = $fopen(vectors, "r");
        if (fd == 0) $fatal(1, "cannot open vectors");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h\n", f0, f1, f2, f3);
            if (n == 4) begin
                rows = rows + 1;
                case (f0)
                    1: rom[f1] = f2;
                    2: flash[f1] = f2;
                    3: otp_digest[255 - 32 * f1 -: 32] = f2;
                    4: otp_key[127 - 32 * f1 -: 32] = f2;
                    5: begin otp_min_version = f1[7:0]; lifecycle = f2[1:0]; end
                    6: begin ev_ref[events] = f1; ev_delay[events] = f2; ev_kind[events] = f3; events = events + 1; end
                    7: case (f1)
                        1: exp_status = f2[7:0];
                        2: exp_halt = f2;
                        3: may_exec = f2[0];
                        4: exec_lo = f2;
                        5: exec_hi = f2;
                        6: exp_debug = f2[0];
                        7: max_cycles = f2;
                        default: $fatal(1, "unknown expectation");
                    endcase
                    8: exp_ram[f1] = f2;
                    default: $fatal(1, "unknown row");
                endcase
            end else if (n != -1) $fatal(1, "malformed row");
        end
        $fclose(fd);
        repeat (4) @(negedge clk);
        rst_n = 1;
        released_at = cycle;
    end

    always @(negedge clk) begin
        cycle = cycle + 1;
        // 1. Nothing granted survives a reset, and no verdict is shown before a check starts.
        if (!rst_n && (boot_status !== 8'd0 || debug_enable !== 1'b0)) fail("BOOT_RESET");
        if (rst_n && !started && (boot_status[7:1] !== 7'd0 || debug_enable !== 1'b0)) fail("BOOT_RESET");
        if (!rst_n) begin
            verdict_seen = 0; started = 0; prev_busy = 0;
        end else if (released_at >= 0 && cycle > released_at + 1) begin
            if ((^{debug_enable, boot_status, ret_valid, halted, bus_error}) === 1'bx) fail("BOOT_X");
            // 2. The verdict, once given, is the expected one and does not change.
            if (boot_status[0] && !prev_busy) begin starts = starts + 1; if (t_start < 0) t_start = cycle; end
            if (boot_status[0]) started = 1;
            prev_busy = boot_status[0];
            if (boot_status[2:1] != 2'b00) begin
                if (!verdict_seen) begin
                    verdict_seen = 1; seen_status = boot_status;
                    if (boot_status !== exp_status) fail("BOOT_VERDICT");
                end else if (boot_status !== seen_status) fail("BOOT_VERDICT");
            end
            // 3. Debug only after an expected PASS, and only where the lifecycle allows it.
            if (debug_enable === 1'b1) begin
                debug_seen = 1;
                if (!(verdict_seen && exp_status == 8'h02 && allows)) fail("BOOT_DEBUG");
            end
            // 4. Each retired instruction.
            if (ret_valid) begin
                if (in_flash) begin
                    if (ret_insn == EBREAK) begin
                        if (boot_status[0]) c_blocked_check = 1;
                        if (boot_status[2]) c_blocked_fail = 1;
                        if (boot_status[1] && ret_pc == exec_hi) c_tail = 1;
                        if (boot_status[1] && ret_pc == 32'h00001000) c_header = 1;
                    end else begin
                        if (!may_exec || ret_pc < exec_lo || ret_pc >= exec_hi) fail("BOOT_EXEC");
                        if (t_image < 0) t_image = cycle;
                    end
                end
                if (key_load) begin
                    if (ret_mem_data !== (in_flash && may_exec ? key_word : 32'd0)) fail("BOOT_KEY");
                    if (in_flash && ret_mem_data != 0) c_key_granted = 1;
                    if (!in_flash && boot_status[2]) c_key_denied = 1;
                end
                if (ret_mem == 2'd1 && ret_mem_addr == 32'h4000010c) begin
                    if (in_flash) c_lc_secure = 1; else c_lc_refused = 1;
                end
                if (ret_mem == 2'd2 && ret_mem_addr == 32'h40000004) c_forge = 1;
                if (ret_mem == 2'd2 && ret_mem_addr == 32'h40000000 && verdict_seen) c_restart = 1;
                if (ret_mem == 2'd2 && ret_mem_addr >= 32'h00002000 && ret_mem_addr < 32'h0000201c) begin
                    shadow[ret_mem_addr[4:2]] = ret_mem_data;
                    shadow_written[ret_mem_addr[4:2]] = 1'b1;
                end
                if (ret_pc == 32'd4) irqs = irqs + 1;
                if (ret_insn == EBREAK) last_ebreak = ret_pc;
            end
            if (bus_error) bus_errors = bus_errors + 1;
            // 5. The end: stopped, the verdict given, and a few clocks for the last writes.
            if (halted && verdict_seen && !finished) begin
                settle = settle + 1;
                if (settle == 4) finished = 1;
            end
        end
        // 6. Scheduled interrupts and resets. Nonblocking, so they take effect after this clock was judged.
        irq_req <= 0;
        for (i = 0; i < events; i = i + 1) if (!ev_fired[i]) begin
            if ((ev_ref[i] == 1 && t_start >= 0 && cycle == t_start + ev_delay[i]) ||
                (ev_ref[i] == 2 && t_image >= 0 && cycle == t_image + ev_delay[i])) begin
                ev_fired[i] = 1;
                if (ev_kind[i] == 1) begin
                    irq_req <= 1;
                    if (boot_status[0]) c_irq_check = 1;
                end else begin
                    rst_n <= 0; reset_left = 3;
                    if (boot_status[0]) c_reset_check = 1;
                    if (t_image >= 0) c_reset_image = 1;
                end
            end
        end
        if (reset_left > 0) begin
            reset_left = reset_left - 1;
            if (reset_left == 0) rst_n <= 1;
        end
        if (cycle > max_cycles) fail("BOOT_TIMEOUT");
        if (finished) begin
            finished = 0;
            if (last_ebreak !== exp_halt) fail("BOOT_HALT");
            for (i = 0; i < 7; i = i + 1)
                if (!shadow_written[i] || shadow[i] !== exp_ram[i]) fail("BOOT_RAM");
            if (debug_enable !== exp_debug || (exp_debug && !debug_seen)) fail("BOOT_DEBUG");
            if (boot_status !== exp_status) fail("BOOT_VERDICT");
            case (exp_status)
                8'h02: $display("COVER verdict/pass");
                8'h14: $display("COVER verdict/fail-magic");
                8'h24: $display("COVER verdict/fail-length");
                8'h34: $display("COVER verdict/fail-rollback");
                8'h44: $display("COVER verdict/fail-digest");
                default: begin end
            endcase
            if (exp_status == 8'h02 && flash[0][7:0] == IMG_MAX) $display("COVER boundary/length-max");
            if (exp_status == 8'h24 && flash[0][7:0] == 0) $display("COVER boundary/length-zero");
            if (exp_status == 8'h24 && flash[0][1:0] != 0) $display("COVER boundary/length-unaligned");
            if (exp_status == 8'h24 && flash[0][7:0] == IMG_MAX + 4) $display("COVER boundary/length-over");
            if (exp_status == 8'h02 && flash[0][15:8] == otp_min_version) $display("COVER boundary/version-equal");
            if (exp_status == 8'h34 && flash[0][15:8] + 1 == otp_min_version) $display("COVER boundary/version-below");
            if (c_blocked_check) $display("COVER gate/blocked-during-check");
            if (c_blocked_fail) $display("COVER gate/blocked-after-fail");
            if (c_tail) $display("COVER gate/blocked-past-payload");
            if (c_header) $display("COVER gate/header-not-executable");
            if (c_key_granted) $display("COVER key/granted");
            if (c_key_denied) $display("COVER key/denied");
            if (c_lc_secure) $display("COVER lifecycle/secure-read");
            if (c_lc_refused && bus_errors > 0) $display("COVER lifecycle/refused");
            if (c_forge) $display("COVER verdict/forge-refused");
            if (c_restart && starts == 1) $display("COVER verdict/restart-ignored");
            if (debug_seen) $display("COVER debug/enabled");
            if (exp_status == 8'h02 && !allows) $display("COVER debug/held-by-lifecycle");
            if (c_irq_check && irqs > 0) $display("COVER irq/during-check");
            if (c_reset_check) $display("COVER reset/during-check");
            if (c_reset_image) $display("COVER reset/during-image");
            $display("COUNT starts=%0d", starts);
            $display("COUNT irqs=%0d", irqs);
            $display("COUNT bus_errors=%0d", bus_errors);
            $display("RESULT PASS checks=%0d", rows);
            $finish;
        end
    end
endmodule
