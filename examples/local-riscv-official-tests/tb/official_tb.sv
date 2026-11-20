`timescale 1ns/1ps
// One memory for instructions and data, loaded with a linked test image. The run ends when
// the core halts on the EBREAK that follows the store to tohost. Every retired instruction is
// written to the trace file, which the runner compares with the instruction set simulator.
module official_tb;
    parameter MUTATION = 0, PREDICT = 0, TRAPS = 1, PRIV = 0, WAITS = 0;
    localparam WORDS = 16384;                 // 64 KiB, the physical memory of the PRIV configuration
    localparam IRQ_W = PRIV != 0 ? 3 : 1;
    reg clk = 0, rst_n = 0, dmem_ready = 1, running = 0;
    wire [IRQ_W-1:0] irq = {IRQ_W{1'b0}};     // the tests use no interrupts
    wire [31:0] imem_addr, dmem_addr, dmem_wdata, ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data;
    wire dmem_valid, dmem_we, ret_valid, halted;
    wire [4:0] ret_rd;
    wire [1:0] ret_mem;
    wire [31:0] perf_ctrl, perf_flush;
    wire [3:0] dmem_be;
    reg [31:0] memory [0:WORDS-1];
    wire [31:0] imem_data = memory[imem_addr[15:2]];
    wire [31:0] dmem_rdata = dmem_ready ? memory[dmem_addr[15:2]] : 32'hdeadbeef;
    rv32i_core #(.MUTATION(MUTATION), .PREDICT(PREDICT), .TRAPS(TRAPS), .PRIV(PRIV)) dut(
        .clk(clk), .rst_n(rst_n), .irq(irq), .imem_addr(imem_addr), .imem_data(imem_data),
        .dmem_valid(dmem_valid), .dmem_we(dmem_we), .dmem_addr(dmem_addr), .dmem_wdata(dmem_wdata),
        .dmem_be(dmem_be), .dmem_rdata(dmem_rdata), .dmem_ready(dmem_ready),
        .ret_valid(ret_valid), .ret_pc(ret_pc), .ret_insn(ret_insn), .ret_wdata(ret_wdata),
        .ret_mem_addr(ret_mem_addr), .ret_mem_data(ret_mem_data), .ret_rd(ret_rd), .ret_mem(ret_mem),
        .perf_ctrl(perf_ctrl), .perf_flush(perf_flush), .halted(halted));
    always #5 clk = ~clk;
    integer fd, trace, n, i, lanes, rows = 0, retired = 0, cycles = 0, limit = 0, tohost_writes = 0, waiting = 0;
    integer tohost = 0;                       // byte address of the tohost word
    reg [31:0] word;
    string image, trace_name, wave;
    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $display("STATE retired=%0d cycles=%0d pc=%h tohost=%h writes=%0d", retired, cycles, ret_pc,
                     memory[tohost >> 2], tohost_writes);
            $fclose(trace);
            $fatal(1, "official test bench stopped");
        end
    endtask
    initial begin
        if (!$value$plusargs("IMAGE=%s", image) || !$value$plusargs("TRACE=%s", trace_name) ||
            !$value$plusargs("TOHOST=%d", tohost) || !$value$plusargs("LIMIT=%d", limit))
            $fatal(1, "arguments required");
        if ($value$plusargs("WAVE=%s", wave)) begin $dumpfile(wave); $dumpvars(0, official_tb); end
        for (i = 0; i < WORDS; i = i + 1) memory[i] = 0;
        fd = $fopen(image, "r"); if (!fd) $fatal(1, "image missing");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h\n", word);
            if (n != 1 || rows >= WORDS) $fatal(1, "bad image");
            memory[rows] = word; rows = rows + 1;
        end
        $fclose(fd);
        if (tohost % 4 != 0 || tohost >> 2 >= WORDS) $fatal(1, "bad tohost address");
        trace = $fopen(trace_name, "w"); if (!trace) $fatal(1, "trace cannot be written");
        repeat (2) @(negedge clk);
        rst_n = 1; running = 1;
        wait (!running);
        $fclose(trace);
        if (tohost_writes != 1) fail("OT_TOHOST_WRITES");
        if ((^memory[tohost >> 2]) === 1'bx) fail("OT_X");
        $display("TOHOST %h", memory[tohost >> 2]);
        $display("RETIRED %0d", retired);
        $display("CYCLES %0d", cycles);
        $display("RESULT DONE words=%0d", rows);
        $finish;
    end
    // With WAITS, every access to the data side waits one cycle.
    always @(negedge clk) if (running) begin
        if (dmem_valid === 1'b1 && WAITS != 0 && !waiting) begin dmem_ready <= 0; waiting = 1; end
        else dmem_ready <= 1;
        if (dmem_valid !== 1'b1) waiting = 0;
    end
    always @(posedge clk) if (running && dmem_valid === 1'b1 && dmem_ready) begin
        if (dmem_we) begin
            for (lanes = 0; lanes < 4; lanes = lanes + 1)
                if (dmem_be[lanes]) memory[dmem_addr[15:2]][8 * lanes +: 8] <= dmem_wdata[8 * lanes +: 8];
            if (dmem_addr[15:2] == tohost[15:2]) tohost_writes = tohost_writes + 1;
        end
        waiting = 0;
    end
    always @(negedge clk) if (running) begin
        cycles = cycles + 1;
        if ((^{ret_valid, halted, dmem_valid}) === 1'bx) fail("OT_X");
        if (dmem_valid === 1'b1 && ((^{dmem_we, dmem_addr, dmem_be}) === 1'bx || (dmem_we && (^dmem_wdata) === 1'bx))) fail("OT_X");
        if (ret_valid) begin
            if ((^{ret_pc, ret_insn, ret_rd, ret_wdata, ret_mem}) === 1'bx) fail("OT_X");
            $fdisplay(trace, "%h %h %h %h %h %h %h", ret_pc, ret_insn, ret_rd, ret_wdata, ret_mem,
                      ret_mem != 0 ? ret_mem_addr : 32'd0, ret_mem != 0 ? ret_mem_data : 32'd0);
            retired = retired + 1;
        end
        if (halted) running <= 0;
        else if (cycles > limit) fail("OT_TIMEOUT");
    end
endmodule
