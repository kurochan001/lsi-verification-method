`timescale 1ns/1ps
// Applies one cycle per row and compares the outputs with the reference. After every cycle it
// also walks the free list and every queue through the next-pointer table and counts the places
// of each buffer, without the reference: each buffer must be in exactly one place.
module buffer_manager_tb;
    parameter MUTATION = 0, NB = 16, NQ = 4;
    localparam BW = $clog2(NB), QW = $clog2(NQ), NL = NQ + 1;
    localparam RESET = 0, CYCLE = 1;

    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg enq_valid = 0, deq_valid = 0, rel_valid = 0;
    reg [QW-1:0] enq_q = 0, deq_q = 0;
    reg [BW-1:0] rel_id = 0;
    wire enq_ready, deq_ready, rel_ready;
    wire [BW-1:0] enq_id, deq_id, free_head_o, free_tail_o;
    wire [BW:0] free_count;
    wire [NQ*(BW+1)-1:0] q_count_o;
    wire [NB*BW-1:0] next_o;
    wire [NQ*BW-1:0] q_head_o, q_tail_o;
    wire [NB-1:0] held_o;

    buffer_manager #(.MUTATION(MUTATION), .NB(NB), .NQ(NQ)) dut(
        .clk(clk), .rst_n(rst_n),
        .enq_valid(enq_valid), .enq_q(enq_q), .enq_ready(enq_ready), .enq_id(enq_id),
        .deq_valid(deq_valid), .deq_q(deq_q), .deq_ready(deq_ready), .deq_id(deq_id),
        .rel_valid(rel_valid), .rel_id(rel_id), .rel_ready(rel_ready),
        .free_count(free_count), .q_count_o(q_count_o), .next_o(next_o),
        .free_head_o(free_head_o), .free_tail_o(free_tail_o),
        .q_head_o(q_head_o), .q_tail_o(q_tail_o), .held_o(held_o));

    integer fd, n, checks = 0, cycles = 0, limit;
    integer enqs = 0, deqs = 0, releases = 0, refused = 0, resets = 0;
    reg [31:0] v [0:17];
    reg failed = 0;
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

    // A row that never ends would hang the run: the watchdog has a label of its own.
    always @(posedge clk) begin
        cycles = cycles + 1;
        if (cycles > limit && !failed) fail("BM_TIMEOUT");
    end

    // The places of every buffer, from the tables alone.
    integer l, s, b, steps;
    integer places [0:NB-1];
    reg [BW-1:0] p, last, tail;
    reg link_bad;
    task check_structure;
        begin
            if (^{free_head_o, free_tail_o, free_count, q_head_o, q_tail_o, q_count_o, held_o, next_o} === 1'bx)
                fail("BM_X");
            for (b = 0; b < NB; b = b + 1) places[b] = held_o[b] ? 1 : 0;
            link_bad = 0;
            for (l = 0; l < NL; l = l + 1) begin
                if (l == 0) begin p = free_head_o; tail = free_tail_o; steps = free_count; end
                else begin
                    p = q_head_o[(l - 1)*BW +: BW]; tail = q_tail_o[(l - 1)*BW +: BW];
                    steps = q_count_o[(l - 1)*(BW+1) +: BW+1];
                end
                if (steps > NB) begin link_bad = 1; steps = NB; end
                last = p;
                for (s = 0; s < steps; s = s + 1) begin
                    places[p] = places[p] + 1;
                    last = p;
                    p = next_o[p*BW +: BW];
                end
                if (steps != 0 && last !== tail) link_bad = 1;
            end
            // A broken link is reported first: it causes both a lost and a doubled buffer.
            if (link_bad) fail("BM_LINK");
            for (b = 0; b < NB; b = b + 1) if (places[b] > 1) fail("BM_DOUBLE");
            for (b = 0; b < NB; b = b + 1) if (places[b] == 0) fail("BM_LEAK");
        end
    endtask

    task check_counts;
        begin
            if (free_count !== v[12][BW:0]) fail("BM_COUNT");
            for (l = 0; l < NQ; l = l + 1)
                if (q_count_o[l*(BW+1) +: BW+1] !== v[13 + l][BW:0]) fail("BM_COUNT");
        end
    endtask

    task report(input [31:0] flags);
        begin
            if (flags[0]) $display("COVER enq/accepted");
            if (flags[1]) $display("COVER enq/refused-full");
            if (flags[2]) $display("COVER deq/accepted");
            if (flags[3]) $display("COVER deq/refused-empty");
            if (flags[4]) $display("COVER release/accepted");
            if (flags[5]) $display("COVER release/twice");
            if (flags[6]) $display("COVER release/queued");
            if (flags[7]) $display("COVER same/one");
            if (flags[8]) $display("COVER same/many");
            if (flags[9]) $display("COVER free/swap-one");
            if (flags[10]) $display("COVER free/refill-empty");
            if (flags[11]) $display("COVER cycle/three");
            if (flags[12]) $display("COVER cycle/idle");
            if (flags[13]) $display("COVER held/all");
            if (flags[14]) $display("COVER queue/last");
            if (flags[15]) $display("COVER enq/reuse");
            if (flags[16]) $display("COVER reset/busy");
        end
    endtask

    initial begin
        limit = 1000;
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, buffer_manager_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "vectors missing");
        @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                        v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11],
                        v[12], v[13], v[14], v[15], v[16], v[17]);
            if (n != 18) $fatal(1, "bad row");
            limit = cycles + 8;
            case (v[0])
                RESET: begin
                    enq_valid = 0; deq_valid = 0; rel_valid = 0;
                    rst_n = 0;
                    @(negedge clk);
                    rst_n = 1;
                    resets = resets + 1;
                    check_structure;
                    check_counts;
                    if (held_o !== {NB{1'b0}}) fail("BM_RESET");
                    report(v[17]);
                end
                CYCLE: begin
                    enq_valid = v[1][0]; enq_q = v[2][QW-1:0];
                    deq_valid = v[3][0]; deq_q = v[4][QW-1:0];
                    rel_valid = v[5][0]; rel_id = v[6][BW-1:0];
                    #1;
                    if (enq_ready === 1'bx || deq_ready === 1'bx || rel_ready === 1'bx) fail("BM_X");
                    // The readies are those of the inputs, also when nothing is requested.
                    if (enq_ready !== v[7][0]) fail("BM_FULL");
                    if (deq_ready !== v[9][0]) fail("BM_EMPTY");
                    if (rel_ready !== v[11][0]) fail("BM_RELEASE");
                    if (enq_ready && enq_id !== v[8][BW-1:0]) fail("BM_ID");
                    if (deq_ready && deq_id !== v[10][BW-1:0]) fail("BM_ID");
                    if (enq_valid && enq_ready) enqs = enqs + 1;
                    if (deq_valid && deq_ready) deqs = deqs + 1;
                    if (rel_valid && rel_ready) releases = releases + 1;
                    if (rel_valid && !rel_ready) refused = refused + 1;
                    @(negedge clk);
                    enq_valid = 0; deq_valid = 0; rel_valid = 0;
                    check_structure;
                    check_counts;
                    report(v[17]);
                end
                default: $fatal(1, "unknown operation");
            endcase
            checks = checks + 1;
        end
        @(negedge clk);
        $display("COUNT steps=%0d", checks);
        $display("COUNT enqs=%0d", enqs);
        $display("COUNT deqs=%0d", deqs);
        $display("COUNT releases=%0d", releases);
        $display("COUNT refused=%0d", refused);
        $display("COUNT resets=%0d", resets);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
