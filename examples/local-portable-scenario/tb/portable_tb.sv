`timescale 1ns/1ps
// One scenario, one realization per run. The first row chooses the realization:
//   block: the bench itself executes the actions against the DMA alone, with its own memory
//          that answers after WAIT clocks and, when asked, also refuses every third clock;
//   soc:   the CPU of scn_soc executes the program generated from the same scenario.
// Both realizations end with a result record (one word per wait and per check) and memory;
// the bench compares both with the same expected rows. While the run goes on it checks the
// memory port of the DMA (block) and unknown values (both), and notes what it observes.
module portable_tb;
    parameter MUTATION = 0, WAIT = 0;
    localparam [31:0] EBREAK = 32'h00100073, DONE = 32'h5CE7E7D0, TIMEOUT = 32'hDEAD0000;
    localparam integer BLOCK_POLLS = 1500;
    reg clk = 0;
    always #5 clk = ~clk;

    // ---- block realization: the DMA with the bench's memory ----
    reg b_rst_n = 0, b_valid = 0, b_we = 0, stall = 0;
    reg [7:0] b_addr = 0;
    reg [31:0] b_wdata = 0;
    wire [31:0] b_rdata, m_wdata, m_rdata;
    wire m_valid, m_we, m_ready;
    wire [7:0] m_addr;
    wire [1:0] b_irq, b_busy;
    reg [31:0] bmem [0:255];
    reg [3:0] bwait = 0;
    reg [1:0] third = 0;
    assign m_ready = {28'd0, bwait} >= WAIT && !(stall && third == 2'd0);
    assign m_rdata = bmem[m_addr];
    scn_dma #(.MUTATION(MUTATION)) blk (
        .clk(clk), .rst_n(b_rst_n), .reg_valid(b_valid), .reg_we(b_we), .reg_addr(b_addr), .reg_wdata(b_wdata),
        .reg_rdata(b_rdata), .mem_valid(m_valid), .mem_we(m_we), .mem_addr(m_addr), .mem_wdata(m_wdata),
        .mem_rdata(m_rdata), .mem_ready(m_ready), .irq(b_irq), .busy_out(b_busy));
    always @(posedge clk) begin
        if (m_valid && m_we && m_ready) bmem[m_addr] <= m_wdata;
        if (!b_rst_n || !m_valid || m_ready) bwait <= 0;
        else if ({28'd0, bwait} < WAIT) bwait <= bwait + 4'd1;
        third <= third == 2'd2 ? 2'd0 : third + 2'd1;
    end

    // ---- SoC realization ----
    reg s_rst_n = 0;
    reg [31:0] rom [0:4095];
    reg [7:0] dbg_addr = 0;
    wire [31:0] fetch_addr, dbg_data, ret_pc, ret_insn, ret_mem_addr, ret_mem_data;
    wire [31:0] fetch_data = fetch_addr[31:14] == 18'd0 ? rom[fetch_addr[13:2]] : EBREAK;
    wire ret_valid, halted, s_stall;
    wire [1:0] ret_mem, s_irq, s_busy;
    scn_soc #(.WAIT(WAIT), .MUTATION(MUTATION)) soc (
        .clk(clk), .rst_n(s_rst_n), .fetch_addr(fetch_addr), .fetch_data(fetch_data), .dbg_addr(dbg_addr),
        .dbg_data(dbg_data), .ret_valid(ret_valid), .ret_pc(ret_pc), .ret_insn(ret_insn),
        .ret_mem_addr(ret_mem_addr), .ret_mem_data(ret_mem_data), .ret_mem(ret_mem), .halted(halted),
        .dma_irq(s_irq), .dma_busy(s_busy), .dma_stall(s_stall));

    // ---- rows ----
    integer fd, n, rows = 0, i, k, mode = 0, acts = 0, mems = 0, records = 0, copies_expected = 0;
    integer max_cycles = 20000, cycle = 0;
    reg [31:0] f0, f1, f2, f3, signature, word;
    string vectors, wave;
    reg [31:0] act_op [0:4095];
    reg [31:0] act_a [0:4095];
    reg [31:0] act_b [0:4095];
    reg [31:0] exp_rec [0:31];
    reg [31:0] got_rec [0:31];
    reg [31:0] exp_addr [0:255];
    reg [31:0] exp_val [0:255];
    reg goal_on [0:31];

    // ---- observation ----
    integer made = 0, copies = 0, polls = 0, acks = 0, timeouts = 0, rec_stores = 0;
    reg running = 0, seen_both = 0, seen_ch1_first = 0, seen_stall = 0, seen_contention = 0;
    reg prev_wait = 0, prev_we = 0;
    reg [7:0] prev_addr = 0;
    reg [31:0] prev_wdata = 0;
    reg [1:0] prev_irq = 0;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "cycle=%0d", cycle);
        end
    endtask

    function automatic string goal_name(input integer index);
        case (index)
            0: goal_name = "action/fill";
            1: goal_name = "action/copy-ch0";
            2: goal_name = "action/copy-ch1";
            3: goal_name = "action/wait";
            4: goal_name = "action/check";
            5: goal_name = "concurrent/two-copies";
            6: goal_name = "concurrent/fill-during-copy";
            7: goal_name = "concurrent/check-during-copy";
            8: goal_name = "conflict/channel-reuse";
            9: goal_name = "conflict/read-after-copy";
            10: goal_name = "conflict/shared-source";
            11: goal_name = "order/wait-reversed";
            12: goal_name = "error/len-zero";
            13: goal_name = "error/len-over";
            14: goal_name = "error/range";
            15: goal_name = "boundary/len-one";
            16: goal_name = "boundary/len-max";
            17: goal_name = "boundary/last-region";
            default: goal_name = "";
        endcase
    endfunction

    task reg_write(input [7:0] addr, input [31:0] value);
        begin
            b_valid = 1; b_we = 1; b_addr = addr; b_wdata = value;
            @(negedge clk);
            b_valid = 0; b_we = 0;
            @(negedge clk);   // an idle clock between accesses
        end
    endtask

    task run_block;
        integer got, waited_polls;
        begin
            repeat (3) @(negedge clk);
            b_rst_n = 1;
            @(negedge clk);
            running = 1;
            for (i = 0; i < acts; i = i + 1) begin
                case (act_op[i])
                    1: bmem[act_a[i][7:0]] = act_b[i];
                    2: begin
                        reg_write(act_a[i][7:0], act_b[i]);
                        if (act_a[i][7:5] == 3'd0 && act_a[i][3:0] == 4'hC) copies = copies + 1;
                    end
                    3: begin
                        got = 0; waited_polls = 0;
                        while (!got && waited_polls < BLOCK_POLLS) begin
                            b_addr = 8'h20; #1;
                            polls = polls + 1; waited_polls = waited_polls + 1;
                            if (b_rdata[act_a[i][0]] === 1'b1) got = 1;
                            else @(negedge clk);
                        end
                        if (got) begin
                            reg_write(8'h20, act_a[i][0] ? 32'd2 : 32'd1);
                            acks = acks + 1;
                            b_addr = {3'd0, act_a[i][0], 4'hC}; #1;
                            got_rec[made] = b_rdata;
                        end else begin
                            got_rec[made] = TIMEOUT | act_b[i];
                            timeouts = timeouts + 1;
                        end
                        made = made + 1;
                    end
                    4: begin
                        signature = 0;
                        for (k = 0; k < act_b[i]; k = k + 1)
                            signature = {signature[30:0], signature[31]} ^ bmem[act_a[i][7:0] + k[7:0]];
                        got_rec[made] = signature;
                        made = made + 1;
                    end
                    default: i = acts;   // END
                endcase
            end
            repeat (4) @(negedge clk);
            running = 0;
        end
    endtask

    task run_soc;
        begin
            repeat (3) @(negedge clk);
            s_rst_n = 1;
            running = 1;
            while (halted !== 1'b1) @(negedge clk);
            repeat (4) @(negedge clk);
            running = 0;
            for (k = 0; k < 30; k = k + 1) begin dbg_addr = k[7:0]; #1; got_rec[k] = dbg_data; end
            dbg_addr = 8'd31; #1;
            if (dbg_data !== DONE) fail("SCN_RESULT");
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave))
            $fatal(1, "missing run arguments");
        $dumpfile(wave);
        $dumpvars(1, portable_tb);
        for (i = 0; i < 4096; i = i + 1) rom[i] = EBREAK;
        for (i = 0; i < 32; i = i + 1) goal_on[i] = 0;
        fd = $fopen(vectors, "r");
        if (fd == 0) $fatal(1, "cannot open vectors");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h\n", f0, f1, f2, f3);
            if (n == 4) begin
                rows = rows + 1;
                case (f0)
                    1: mode = f1;
                    2: rom[f1] = f2;
                    3: begin act_op[acts] = f1; act_a[acts] = f2; act_b[acts] = f3; acts = acts + 1; end
                    4: begin exp_rec[f1] = f2; end
                    5: begin exp_addr[mems] = f1; exp_val[mems] = f2; mems = mems + 1; end
                    6: case (f1)
                        1: max_cycles = f2;
                        2: records = f2;
                        3: copies_expected = f2;
                        4: stall = f2[0];
                        default: $fatal(1, "unknown meta row");
                    endcase
                    7: goal_on[f1] = 1;
                    default: $fatal(1, "unknown row");
                endcase
            end else if (n != -1) $fatal(1, "malformed row");
        end
        $fclose(fd);
        if (mode == 1) run_block;
        else if (mode == 2) run_soc;
        else $fatal(1, "unknown realization");
        // ---- the end: record first, then memory ----
        if (mode == 1 && made != records) fail("SCN_RESULT");
        for (k = 0; k < records; k = k + 1) if (got_rec[k] !== exp_rec[k]) fail("SCN_RESULT");
        for (k = 0; k < mems; k = k + 1) begin
            if (mode == 1) word = bmem[exp_addr[k][7:0]];
            else begin dbg_addr = exp_addr[k][7:0]; #1; word = dbg_data; end
            if (word !== exp_val[k]) fail("SCN_MEMORY");
        end
        for (k = 0; k < 18; k = k + 1) if (goal_on[k]) $display("COVER %s", goal_name(k));
        if (mode == 1) $display("COVER mode/block");
        else $display("COVER mode/soc");
        if (seen_both) $display("COVER observed/both-active");
        if (seen_ch1_first) $display("COVER observed/ch1-first");
        if (polls > acks + timeouts) $display("COVER observed/poll-repeated");
        if (seen_stall) $display("COVER observed/memory-stall");
        if (seen_contention) $display("COVER observed/ram-contention");
        $display("COUNT records=%0d", mode == 1 ? made : rec_stores);
        $display("COUNT copies=%0d", copies);
        $display("RESULT PASS checks=%0d", rows);
        $finish;
    end

    // ---- every clock ----
    wire [1:0] busy = mode == 1 ? b_busy : s_busy;
    wire [1:0] irq = mode == 1 ? b_irq : s_irq;
    always @(negedge clk) begin
        cycle = cycle + 1;
        if (cycle > max_cycles) fail("SCN_TIMEOUT");
        if (running) begin
            if (mode == 1) begin
                if ((^{m_valid, b_irq, b_busy}) === 1'bx || (m_valid && (^{m_we, m_addr}) === 1'bx)) fail("SCN_X");
                // A request that waits stays the same until it is taken.
                if (prev_wait && (m_valid !== 1'b1 || m_we !== prev_we || m_addr !== prev_addr ||
                                  (prev_we && m_wdata !== prev_wdata))) fail("SCN_PORT");
                prev_wait = m_valid && !m_ready; prev_we = m_we; prev_addr = m_addr; prev_wdata = m_wdata;
                if (m_valid && !m_ready) seen_stall = 1;
            end else begin
                if ((^{halted, ret_valid, s_irq, s_busy}) === 1'bx) fail("SCN_X");
                if (s_stall) seen_contention = 1;
                if (ret_valid && ret_mem == 2'd1 && ret_mem_addr == 32'h40000020) polls = polls + 1;
                if (ret_valid && ret_mem == 2'd2 && ret_mem_addr == 32'h40000020) acks = acks + 1;
                if (ret_valid && ret_mem == 2'd2 && (ret_mem_addr == 32'h4000000C || ret_mem_addr == 32'h4000001C) &&
                    ret_mem_data[0]) copies = copies + 1;
                if (ret_valid && ret_mem == 2'd2 && ret_mem_addr[31:8] == 24'h000020 && ret_mem_addr[7:0] < 8'h78 &&
                    ret_mem_data[31:16] == TIMEOUT[31:16]) timeouts = timeouts + 1;
                if (ret_valid && ret_mem == 2'd2 && ret_mem_addr[31:8] == 24'h000020 && ret_mem_addr[7:0] < 8'h78) rec_stores = rec_stores + 1;
            end
            if (busy == 2'b11) seen_both = 1;
            if (irq[1] && !prev_irq[1] && busy[0]) seen_ch1_first = 1;
            prev_irq = irq;
        end
    end
endmodule
