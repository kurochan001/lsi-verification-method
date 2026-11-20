`timescale 1ns/1ps
// The core with its debug module, a program, and a debugger on the JTAG pins. Two things run
// side by side: every retired instruction is compared, in order, with the record the ISS
// produced, and the script of the debugger is played scan by scan. Rows have eight columns.
// 0 instruction word, 1 data word, 2 cycle limit, 3 expected retirement (pc, instruction, rd,
// value, memory kind and wait cycles, address, data), 5 expected final data word; script:
// 8 instruction register scan, 9 data register scan (length, bits in, expected bits, mask,
// mode, register, label), 10 poll (length, request, expected, mask, tries), 11 wait until that
// many instructions have retired, 12 idle clock cycles, 13 release the reset of the core,
// 14 credit a goal, 16 a register the debugger wrote.
module debug_tb;
    parameter MUTATION = 0, PREDICT = 0;
    localparam IRQ_WORD = 255;  // a store to this data word sets the interrupt line to its bit 0
    localparam N = 16384, SCRIPT = 16384, IMEM = 16384, DMEM = 256;
    reg clk = 0, rst_n = 0, core_rst_n = 0, dmem_ready = 1, irq = 0;
    reg tck = 0, tms = 1, tdi = 0, trst_n = 1;
    wire tdo;
    wire [31:0] imem_addr, dmem_addr, dmem_wdata, ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data;
    wire dmem_valid, dmem_we, ret_valid, halted, dbg_halted;
    wire [4:0] ret_rd;
    wire [1:0] ret_mem;
    wire [3:0] dmem_be;
    reg [31:0] imem[0:IMEM-1], dmem[0:DMEM-1], e_mem[0:DMEM-1];
    wire [31:0] imem_data = imem[imem_addr[15:2]];
    wire [31:0] dmem_rdata = dmem_ready ? dmem[dmem_addr[9:2]] : 32'hdeadbeef;
    debug_system #(.MUTATION(MUTATION), .PREDICT(PREDICT)) dut(
        .clk(clk), .rst_n(rst_n), .core_rst_n(core_rst_n), .irq(irq), .tck(tck), .tms(tms), .tdi(tdi), .trst_n(trst_n),
        .tdo(tdo), .imem_addr(imem_addr), .imem_data(imem_data), .dmem_valid(dmem_valid), .dmem_we(dmem_we),
        .dmem_addr(dmem_addr), .dmem_wdata(dmem_wdata), .dmem_be(dmem_be), .dmem_rdata(dmem_rdata),
        .dmem_ready(dmem_ready), .ret_valid(ret_valid), .ret_pc(ret_pc), .ret_insn(ret_insn), .ret_wdata(ret_wdata),
        .ret_mem_addr(ret_mem_addr), .ret_mem_data(ret_mem_data), .ret_rd(ret_rd), .ret_mem(ret_mem), .halted(halted),
        .dbg_halted(dbg_halted));
    always #5 clk = ~clk;
    integer fd, n, i, rows = 0, expected = 0, retired = 0, loads = 0, stores = 0, cycles = 0, limit = 0;
    integer accesses = 0, waits = 0, waiting = 0, lanes, mem_rows = 0, steps = 0, at = 0, halts = 0, scans = 0, tries;
    reg ready_now, failed = 0, running = 0, script_done = 0, was_halted = 0, asked_in_wait = 0, matched;
    reg [63:0] v[0:7];
    reg [31:0] e_pc[0:N-1], e_insn[0:N-1], e_wdata[0:N-1], e_addr[0:N-1], e_data[0:N-1], shadow[0:31];
    reg [4:0] e_rd[0:N-1];
    reg [1:0] e_kind[0:N-1];
    reg [3:0] wait_of[0:N-1];
    reg [63:0] s_kind[0:SCRIPT-1], s1[0:SCRIPT-1], s2[0:SCRIPT-1], s3[0:SCRIPT-1], s4[0:SCRIPT-1], s5[0:SCRIPT-1],
               s6[0:SCRIPT-1], s7[0:SCRIPT-1];
    reg [63:0] got, want;
    reg bit_out;
    string vectors, wave;
    function string goal_name(input integer k);  // same order as GOALS in model.py
        case (k)
            0: goal_name = "dtm/idcode";               1: goal_name = "dtm/dtmcs";
            2: goal_name = "halt/before-first-instruction"; 3: goal_name = "halt/request-while-running";
            4: goal_name = "halt/ebreak";              5: goal_name = "halt/ebreak-again";
            6: goal_name = "resume/ack";               7: goal_name = "resume/dpc-moved";
            8: goal_name = "step/sequential";          9: goal_name = "step/taken-branch";
            10: goal_name = "step/load";               11: goal_name = "step/exception";
            12: goal_name = "step/interrupt-masked";   13: goal_name = "step/after-request";
            14: goal_name = "reg/gpr-read";            15: goal_name = "reg/gpr-write-visible";
            16: goal_name = "reg/x0";                  17: goal_name = "reg/dcsr";
            18: goal_name = "reg/dpc";                 19: goal_name = "abstract/busy";
            20: goal_name = "abstract/not-supported";  21: goal_name = "abstract/unknown-register";
            22: goal_name = "abstract/running-hart";   23: goal_name = "abstract/sticky-error";
            default: goal_name = "abstract/clear";
        endcase
    endfunction
    function string label_name(input integer k);  // same order as LABELS in model.py
        case (k)
            0: label_name = "DBG_DATA";   1: label_name = "DBG_DPC";  2: label_name = "DBG_CMDERR";
            3: label_name = "DBG_STATUS"; default: label_name = "DBG_DTM";
        endcase
    endfunction
    // Both sides can find a failure in the same time step; only the first is reported.
    task fail(input string label);
        begin
            if (!failed) begin
                failed = 1;
                $display("CHECK_FAIL %s", label);
                $fatal(1, "retired=%0d script row=%0d pc=%h insn=%h rd=%0d wdata=%h expected pc=%h insn=%h got=%h want=%h",
                       retired, at, ret_pc, ret_insn, ret_rd, ret_wdata, e_pc[retired], e_insn[retired], got, want);
            end
        end
    endtask
    // One TCK period is four clock cycles: the pins change while TCK is low, TDO is read before the rise.
    task tick(input reg mode_bit, input reg data_bit);
        begin
            @(negedge clk); tck = 0; tms = mode_bit; tdi = data_bit;
            repeat (2) @(negedge clk);
            bit_out = tdo; tck = 1;
            @(negedge clk);
        end
    endtask
    task scan_ir(input reg [3:0] value);
        begin
            tick(1, 0); tick(1, 0); tick(0, 0); tick(0, 0);
            for (i = 0; i < 4; i = i + 1) tick(i == 3, value[i]);
            tick(1, 0); tick(0, 0);
        end
    endtask
    task scan_dr(input integer length, input reg [63:0] value);
        begin
            got = 0;
            tick(1, 0); tick(0, 0); tick(0, 0);
            for (i = 0; i < length; i = i + 1) begin tick(i == length - 1, value[i]); got[i] = bit_out; end
            tick(1, 0); tick(0, 0); tick(0, 0);
        end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        // The JTAG pins, the debug module's state, what the core retires and the halts. The clock
        // is left out: it would be most of the file.
        $dumpfile(wave);
        $dumpvars(0, tck, tms, tdi, tdo, trst_n, core_rst_n, irq, ret_valid, ret_pc, ret_insn, ret_rd, ret_wdata, halted,
                  dbg_halted, retired, at, halts, dut.dtm.dmi_req, dut.dtm.dmi_op, dut.dtm.dmi_addr, dut.dtm.dmi_wdata,
                  dut.dm.dmi_rdata, dut.dm.haltreq, dut.dm.resumereq, dut.dm.resumeack, dut.dm.busy, dut.dm.cmderr,
                  dut.dm.data0, dut.dm.command, dut.dm.reg_we);
        for (i = 0; i < IMEM; i = i + 1) imem[i] = 32'h00000013;  // NOP beyond the program
        for (i = 0; i < DMEM; i = i + 1) dmem[i] = 0;
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]);
            if (n != 8) $fatal(1, "bad row");
            rows = rows + 1;
            if ((v[0] == 0 && v[1] >= IMEM) || ((v[0] == 1 || v[0] == 5) && v[1] >= DMEM) || (v[0] == 3 && expected >= N) ||
                (v[0] >= 8 && steps >= SCRIPT)) $fatal(1, "row %0d does not fit the bench memories", rows);
            case (v[0])
                0: imem[v[1]] = v[2][31:0];
                1: dmem[v[1]] = v[2][31:0];
                2: limit = v[1];
                3: begin
                    e_pc[expected] = v[1][31:0]; e_insn[expected] = v[2][31:0]; e_rd[expected] = v[3][4:0];
                    e_wdata[expected] = v[4][31:0]; e_kind[expected] = v[5][1:0]; e_addr[expected] = v[6][31:0];
                    e_data[expected] = v[7][31:0];
                    if (v[5][1:0] == 1 || v[5][1:0] == 2) begin wait_of[accesses] = v[5][7:4]; accesses = accesses + 1; end
                    expected = expected + 1;
                end
                5: begin e_mem[v[1]] = v[2][31:0]; mem_rows = mem_rows + 1; end
                8, 9, 10, 11, 12, 13, 14, 16: begin
                    s_kind[steps] = v[0]; s1[steps] = v[1]; s2[steps] = v[2]; s3[steps] = v[3]; s4[steps] = v[4];
                    s5[steps] = v[5]; s6[steps] = v[6]; s7[steps] = v[7]; steps = steps + 1;
                end
                default: $fatal(1, "bad row type");
            endcase
        end
        accesses = 0;
        #1 trst_n = 0;  // the TAP resets on the falling edge
        repeat (2) @(negedge clk);
        rst_n = 1; trst_n = 1; running = 1;
        tick(0, 0);  // Test-Logic-Reset to Run-Test/Idle
        // The debugger's script.
        for (at = 0; at < steps; at = at + 1) begin
            case (s_kind[at])
                8: scan_ir(s1[at][3:0]);
                9: begin
                    scan_dr(s1[at], s2[at]);
                    scans = scans + 1;
                    // Mode 1: the data field is the address of the next instruction to retire.
                    // Mode 2: the data field is the value the retired instructions gave a register.
                    want = s5[at] == 1 ? {30'd0, e_pc[retired], 2'd0} : s5[at] == 2 ? {30'd0, shadow[s6[at][4:0]], 2'd0} : s3[at];
                    if (s5[at] != 0 ? got[33:0] !== want[33:0] : ((got ^ want) & s4[at]) !== 64'd0) fail(label_name(s7[at]));
                end
                10: begin
                    matched = 0; want = s3[at];
                    for (tries = 0; tries < s5[at] && !matched; tries = tries + 1) begin
                        scan_dr(s1[at], s2[at]);
                        scan_dr(s1[at], 64'd0);
                        matched = ((got ^ want) & s4[at]) === 64'd0;
                    end
                    if (!matched) fail(label_name(s7[at]));
                end
                11: while (retired < s1[at]) @(negedge clk);
                12: repeat (s1[at]) @(negedge clk);
                13: core_rst_n = 1;
                14: $display("COVER %s", goal_name(s1[at]));
                default: shadow[s1[at][4:0]] = s2[at][31:0];
            endcase
        end
        script_done = 1;
        wait (!running);
        // Every word of the data memory, so that a store nothing reads back is checked too.
        if (mem_rows != DMEM) fail("ISS_MEM");
        for (i = 0; i < DMEM; i = i + 1) if (dmem[i] !== e_mem[i]) fail("ISS_MEM");
        $display("COUNT retired=%0d", retired);
        $display("COUNT loads=%0d", loads);
        $display("COUNT stores=%0d", stores);
        $display("COUNT halts=%0d", halts);
        $display("COUNT scans=%0d", scans);
        $display("RESULT PASS checks=%0d", rows);
        $finish;
    end
    // Data memory: the k-th access waits as many cycles as its row says.
    always @(negedge clk) if (running) begin
        if (dmem_valid === 1'b1) begin
            if (!waiting) begin waiting = 1; waits = wait_of[accesses]; end
            else if (waits) waits = waits - 1;
            ready_now = waits == 0;
            dmem_ready <= ready_now;
        end else begin  // no request, or one withdrawn by a trap or by debug mode
            dmem_ready <= 1; waiting = 0;
        end
    end
    always @(posedge clk) if (running && dmem_valid === 1'b1 && dmem_ready) begin
        if (dmem_we) for (lanes = 0; lanes < 4; lanes = lanes + 1)
            if (dmem_be[lanes]) dmem[dmem_addr[9:2]][8 * lanes +: 8] <= dmem_wdata[8 * lanes +: 8];
        if (dmem_we && dmem_addr[9:2] == IRQ_WORD && dmem_be[0]) irq <= dmem_wdata[0];
        waiting = 0; accesses = accesses + 1;
    end
    // Retirement: compare in order. The registers the retired instructions wrote are kept for
    // the debugger's reads at halts whose place is not known beforehand.
    always @(negedge clk) if (running) begin
        cycles = cycles + 1;
        if ((^{ret_valid, halted, dbg_halted, dmem_valid, tdo}) === 1'bx) fail("ISS_X");
        if (ret_valid) begin
            if (retired >= expected) fail("ISS_END");
            if (ret_pc !== e_pc[retired] || ret_insn !== e_insn[retired]) fail("ISS_FLOW");
            if (ret_rd !== e_rd[retired] || ret_wdata !== e_wdata[retired] || ret_mem !== e_kind[retired] ||
                (e_kind[retired] != 0 && (ret_mem_addr !== e_addr[retired] || ret_mem_data !== e_data[retired])))
                fail("ISS_DATA");
            if (e_rd[retired] != 0) shadow[e_rd[retired]] = e_wdata[retired];
            loads = loads + (ret_mem == 1); stores = stores + (ret_mem == 2);
            retired = retired + 1;
        end
        if (dbg_halted && !was_halted) halts = halts + 1;
        was_halted = dbg_halted;
        if (cycles > limit) fail("ISS_END");
        if (halted) begin
            // The program has ended: everything expected has retired. The debugger finishes its script.
            if (retired != expected) fail("ISS_END");
            if (script_done) running <= 0;
        end
    end
    // What a halt request meets in the pipeline, seen in the cycle debug mode is entered.
    always @(negedge clk) if (running && core_rst_n) begin
        if (dut.haltreq && !dbg_halted && dut.cpu.core.dmem_pending) asked_in_wait = 1;
        if (dut.cpu.core.dbg_enter && dut.haltreq) begin
            if (dut.cpu.core.redirect) $display("COVER halt/at-branch-flush");
            if (dut.cpu.core.mem_cause != 4'd0) $display("COVER halt/at-exception");
            if (dut.cpu.core.pend_e && dut.cpu.core.st_mie) $display("COVER halt/at-interrupt");
            if (asked_in_wait) $display("COVER halt/after-memory-wait");
            asked_in_wait = 0;
        end
    end
endmodule
