`timescale 1ns/1ps
// Applies one vector row per cycle and compares every output with the plan. The litmus results
// (final counter, failed SCs, two holders of the lock) are taken from the responses of the DUT.
module atomic_tb;
    parameter GRAIN = 0, MUTATION = 0;
    localparam [2:0] LOAD = 3'd0, STORE = 3'd1, LR = 3'd2, SC = 3'd3, AMO = 3'd4;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0, req_valid = 0, hart = 0;
    reg [2:0] op = 0;
    reg [3:0] fn = 0;
    reg [1:0] address = 0, resp_ready = 0;
    reg [31:0] write_data = 0;
    wire req_ready;
    wire [1:0] resp_valid;
    wire [63:0] resp_data;
    wire [127:0] visible_memory;
    atomic_mem #(.GRAIN(GRAIN), .MUTATION(MUTATION)) dut(.*);

    integer fd, n, h, checks = 0, loads = 0, stores = 0, reservations = 0, sc_success = 0, sc_failure = 0, amos = 0;
    integer program_id = 0, holder = -1, counter;
    reg [1:0] sc_failed = 0;
    reg [2:0] last_op [0:1];
    reg [1:0] last_address [0:1];
    reg [127:0] v [0:16];
    reg [31:0] data, expected;
    reg [2:0] kind;
    reg fire;
    string vectors, wave;

    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d", checks); end
    endtask

    task note_goal(input integer note);
        begin
            case (note)
                1: $display("COVER reason/no-reservation");
                2: $display("COVER reason/other-store");
                3: $display("COVER reason/other-sc");
                4: $display("COVER reason/other-amo");
                5: $display("COVER reason/other-address");
                6: $display("COVER reason/second-sc");
                7: $display("COVER reason/own-store");
                8: $display("COVER reason/neighbour-store");
                9: $display("COVER reason/after-reset");
                10: $display("COVER amo/signed-compare");
                11: $display("COVER reason/own-amo");
                12: $display("COVER reason/new-lr");
                default: ;
            endcase
        end
    endtask

    task amo_goal(input [3:0] code);
        begin
            case (code)
                0: $display("COVER amo/swap");
                1: $display("COVER amo/add");
                2: $display("COVER amo/xor");
                3: $display("COVER amo/and");
                4: $display("COVER amo/or");
                5: $display("COVER amo/min");
                6: $display("COVER amo/max");
                7: $display("COVER amo/minu");
                default: $display("COVER amo/maxu");
            endcase
        end
    endtask

    task litmus_goal;
        begin
            counter = int'(visible_memory[95:64]);
            // Locked, LR/SC and AMO updates never lose an increment; the unprotected programs may.
            if (program_id <= 3 ? counter != 2 : (counter != 1 && counter != 2)) fail("ATOM_LITMUS");
            case (program_id)
                1: $display("COVER litmus/spinlock-%0d-%0d%0d", counter, sc_failed[0], sc_failed[1]);
                2: $display("COVER litmus/lrsc-%0d-%0d%0d", counter, sc_failed[0], sc_failed[1]);
                3: $display("COVER litmus/amoadd-%0d-%0d%0d", counter, sc_failed[0], sc_failed[1]);
                4: $display("COVER litmus/plain-%0d-%0d%0d", counter, sc_failed[0], sc_failed[1]);
                default: $display("COVER litmus/taslock-%0d-%0d%0d", counter, sc_failed[0], sc_failed[1]);
            endcase
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "arguments required");
        $dumpfile(wave);
        $dumpvars(0, atomic_tb);
        fd = $fopen(vectors, "r");
        if (!fd) $fatal(1, "missing input");
        last_op[0] = 0; last_op[1] = 0; last_address[0] = 0; last_address[1] = 0;
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n", v[0], v[1], v[2], v[3], v[4],
                        v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13], v[14], v[15], v[16]);
            if (n != 17) $fatal(1, "bad row");
            rst_n = v[0][0]; req_valid = v[1][0]; hart = v[2][0]; op = v[3][2:0]; fn = v[4][3:0];
            address = v[5][1:0]; write_data = v[6][31:0]; resp_ready = v[7][1:0];
            #1;
            if ((^{req_ready, resp_valid}) === 1'bx || (^visible_memory) === 1'bx) fail("ATOM_X");
            // Not ready although the plan says ready, or the reverse; in the second cycle of an AMO it is the lock.
            if (req_ready !== v[9][0]) fail(v[10][0] ? "ATOM_AMO" : "ATOM_FLOW");
            if (resp_valid !== v[11][1:0]) fail("ATOM_FLOW");
            for (h = 0; h < 2; h = h + 1) if (resp_valid[h]) begin
                data = resp_data[32*h +: 32];
                expected = h == 0 ? v[12][31:0] : v[13][31:0];
                kind = h == 0 ? v[15][2:0] : v[15][6:4];
                if ((^data) === 1'bx) fail("ATOM_X");
                if (data !== expected) fail(kind == SC ? "ATOM_SC" : "ATOM_DATA");
            end
            if (visible_memory !== v[14]) fail("ATOM_MEMORY");

            if (!rst_n) begin
                if (dut.amo_busy !== 1'b0) fail("ATOM_FLOW");
                if (v[8] != 0) begin program_id = int'(v[8]); sc_failed = 0; holder = -1; end
                if (checks != 0) $display("COVER reset/applied");
            end else begin
                fire = req_valid && req_ready;
                if (req_valid && !req_ready && v[10][0]) $display("COVER amo/blocks-requests");
                if (req_valid && !req_ready && !v[10][0] && resp_valid[hart]) $display("COVER response/blocks-own-hart");
                if (resp_valid == 2'b11) $display("COVER response/both-waiting");
                if (|(resp_valid & ~resp_ready)) $display("COVER response/hold");
                if (fire) begin
                    last_op[hart] = op; last_address[hart] = address;
                    note_goal(int'(v[16]));
                    case (op)
                        LOAD: loads = loads + 1;
                        STORE: begin
                            stores = stores + 1;
                            if (program_id == 1 && address == 0 && write_data == 0 && holder == int'(hart)) holder = -1;
                        end
                        LR: begin reservations = reservations + 1; $display("COVER lr/reserved"); end
                        SC: ;
                        default: begin amos = amos + 1; amo_goal(fn); end
                    endcase
                end
                for (h = 0; h < 2; h = h + 1) if (resp_valid[h] && resp_ready[h] && last_op[h] == SC) begin
                    if (resp_data[32*h +: 32] == 0) begin
                        sc_success = sc_success + 1;
                        $display("COVER sc/success");
                        if (program_id == 1 && last_address[h] == 0) begin
                            if (holder != -1) fail("ATOM_MUTEX");  // a second hart took the lock
                            holder = h;
                        end
                    end else begin
                        sc_failure = sc_failure + 1; sc_failed[h] = 1'b1;
                        $display("COVER sc/failure");
                    end
                end
                if (v[8] >= 8) begin litmus_goal(); program_id = 0; end
            end
            @(posedge clk); #1; checks = checks + 1; @(negedge clk);
        end
        $display("COUNT steps=%0d", checks);
        $display("COUNT loads=%0d", loads);
        $display("COUNT stores=%0d", stores);
        $display("COUNT reservations=%0d", reservations);
        $display("COUNT sc_success=%0d", sc_success);
        $display("COUNT sc_failure=%0d", sc_failure);
        $display("COUNT amos=%0d", amos);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
