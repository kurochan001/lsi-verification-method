`timescale 1ns/1ps
// Loads the program and data, then compares every retired instruction, in order, with the
// record the ISS produced. Vector rows: 0 instruction word, 1 data word, 2 cycle limit,
// 3 expected retirement (pc, instruction, rd, value, memory kind, address, data, coverage
// tags, operation index, wait cycles for its memory access).
module core_tb;
    parameter MUTATION = 0;
    localparam N = 16384, IMEM = 16384, DMEM = 256;  // run.py keeps programs within these sizes
    reg clk = 0, rst_n = 0, dmem_ready = 1;
    wire [31:0] imem_addr, dmem_addr, dmem_wdata, ret_pc, ret_insn, ret_wdata, ret_mem_addr, ret_mem_data;
    wire dmem_valid, dmem_we, ret_valid, halted;
    wire [4:0] ret_rd;
    wire [1:0] ret_mem;
    reg [31:0] imem[0:IMEM-1], dmem[0:DMEM-1];
    wire [31:0] imem_data = imem[imem_addr[15:2]];
    wire [31:0] dmem_rdata = dmem_ready ? dmem[dmem_addr[9:2]] : 32'hdeadbeef;
    rv32i_core #(.MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer fd, n, i, rows = 0, expected = 0, retired = 0, loads = 0, stores = 0, cycles = 0, limit = 0;
    integer accesses = 0, waits = 0, waiting = 0;
    reg [31:0] v[0:10];
    reg [31:0] e_pc[0:N-1], e_insn[0:N-1], e_wdata[0:N-1], e_addr[0:N-1], e_data[0:N-1], e_tags[0:N-1];
    reg [4:0] e_rd[0:N-1];
    reg [1:0] e_kind[0:N-1];
    reg [5:0] e_op[0:N-1];
    reg [3:0] wait_of[0:N-1];
    reg [31:0] ops = 0;
    reg running = 0;
    string vectors, wave;
    function string tag_name(input integer k);  // same order as TAGS in run.py
        case (k)
            0: tag_name = "raw/distance-1";       1: tag_name = "raw/distance-2";
            2: tag_name = "raw/distance-3";       3: tag_name = "load/use";
            4: tag_name = "load/store-data";      5: tag_name = "jalr/forwarded-base";
            6: tag_name = "branch/taken";         7: tag_name = "branch/not-taken";
            8: tag_name = "branch/forwarded-operand"; 9: tag_name = "branch/backward";
            10: tag_name = "x0/write-then-read";  11: tag_name = "halt/ebreak";
            default: tag_name = "mem/wait-forwarding";
        endcase
    endfunction
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label);
              $fatal(1, "retired=%0d pc=%h insn=%h rd=%0d wdata=%h expected pc=%h insn=%h rd=%0d wdata=%h",
                     retired, ret_pc, ret_insn, ret_rd, ret_wdata, e_pc[retired], e_insn[retired], e_rd[retired],
                     e_wdata[retired]); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave); $dumpvars(0, core_tb);
        for (i = 0; i < IMEM; i = i + 1) imem[i] = 32'h00000013;  // NOP beyond the program
        for (i = 0; i < DMEM; i = i + 1) dmem[i] = 0;
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10]);
            if (n != 11) $fatal(1, "bad row");
            rows = rows + 1;
            if ((v[0] == 0 && v[1] >= IMEM) || (v[0] == 1 && v[1] >= DMEM) || (v[0] == 3 && expected >= N))
                $fatal(1, "row %0d does not fit the bench memories", rows);
            case (v[0])
                0: imem[v[1]] = v[2];
                1: dmem[v[1]] = v[2];
                2: limit = v[1];
                3: begin
                    e_pc[expected] = v[1]; e_insn[expected] = v[2]; e_rd[expected] = v[3]; e_wdata[expected] = v[4];
                    e_kind[expected] = v[5]; e_addr[expected] = v[6]; e_data[expected] = v[7];
                    e_tags[expected] = v[8]; e_op[expected] = v[9];
                    if (v[5] != 0) begin wait_of[accesses] = v[10]; accesses = accesses + 1; end
                    expected = expected + 1;
                end
                default: $fatal(1, "bad row type");
            endcase
        end
        accesses = 0;
        repeat (2) @(negedge clk);
        rst_n = 1; running = 1;
        wait (!running);
        $display("COUNT retired=%0d", retired);
        $display("COUNT loads=%0d", loads);
        $display("COUNT stores=%0d", stores);
        $display("RESULT PASS checks=%0d", rows);
        $finish;
    end
    // Data memory: the k-th access waits as many cycles as its row says.
    always @(negedge clk) if (running) begin
        if (dmem_valid === 1'b1) begin
            if (!waiting) begin waiting = 1; waits = wait_of[accesses]; end
            else if (waits) waits = waits - 1;
            dmem_ready = waits == 0;
            if (!dmem_ready && dmem_we) $display("COVER mem/wait-store");
            if (!dmem_ready && !dmem_we) $display("COVER mem/wait-load");
        end else dmem_ready = 1;
    end
    always @(posedge clk) if (running && dmem_valid === 1'b1 && dmem_ready) begin
        if (dmem_we) dmem[dmem_addr[9:2]] <= dmem_wdata;
        waiting = 0; accesses = accesses + 1;
    end
    // Retirement: compare in order, then credit the tags of the matched record.
    always @(negedge clk) if (running) begin
        cycles = cycles + 1;
        if ((^{ret_valid, halted, dmem_valid}) === 1'bx) fail("ISS_X");
        if (ret_valid) begin
            if (retired >= expected) fail("ISS_END");
            if (ret_pc !== e_pc[retired] || ret_insn !== e_insn[retired]) fail("ISS_FLOW");
            if (ret_rd !== e_rd[retired] || ret_wdata !== e_wdata[retired] || ret_mem !== e_kind[retired] ||
                (e_kind[retired] != 0 && (ret_mem_addr !== e_addr[retired] || ret_mem_data !== e_data[retired])))
                fail("ISS_DATA");
            for (i = 0; i < 13; i = i + 1) if (e_tags[retired][i]) $display("COVER %s", tag_name(i));
            ops[e_op[retired]] = 1;
            if (&ops) $display("COVER isa/every-instruction");
            loads = loads + (ret_mem == 1); stores = stores + (ret_mem == 2);
            retired = retired + 1;
        end
        if (halted) begin
            if (retired != expected) fail("ISS_END");
            running = 0;
        end else if (cycles > limit) fail("ISS_END");
    end
endmodule
