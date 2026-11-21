// Proof harness. The flip mask is a free input, so one proof covers every stored bit, every
// state and every clock edge. A flip may happen on any edge outside reset, any number of times;
// each edge flips at most FAULT_BITS bits (STATE_ONLY = 1 keeps them in the state code).
// The reference is the lock without faults, written with plain state numbers; it shares no
// code table with the design.
//   ap_match         before the first flip since reset, the outputs equal the reference
//   ap_no_escalation grant only where the reference grants, flips or not
//   ap_detect        from the second edge after the first flip until reset, alarm is set,
//                    except right after a further flip
// PROOF_AIDS = 1 adds the invariants that make k-induction succeed. They are assertions, proved
// together with the rest; they name the hardened code table, so they are compiled only for it.
module fsm_hardening_formal #(parameter HARDENED = 1, MAX_TRIES = 3, MUTATION = 0, FAULT_BITS = 1,
        STATE_ONLY = 0, PROOF_AIDS = 0, ESCALATION_ONLY = 0) (
    input wire clk, rst_n, start, key_ok, relock,
    input wire [(HARDENED != 0 ? 10 : 5) - 1:0] fault
);
    localparam FW = HARDENED != 0 ? 10 : 5;
    localparam SW = HARDENED != 0 ? 6 : 3;
    wire grant, busy, lockout, alarm;
    wire [1:0] fails;
    wire [FW-1:0] regs;
    hardened_lock #(.HARDENED(HARDENED), .MAX_TRIES(MAX_TRIES), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .start(start), .key_ok(key_ok), .relock(relock), .fault_xor(fault),
        .grant(grant), .busy(busy), .lockout(lockout), .alarm(alarm), .fails(fails), .f_regs(regs));

    function [3:0] ones(input [9:0] v);
        integer i;
        begin
            ones = 0;
            for (i = 0; i < 10; i = i + 1) ones = ones + {3'b000, v[i]};
        end
    endfunction

    // The hardened code of each reference state, for the proof aids only.
    function [5:0] code(input [1:0] s);
        case (s)
            2'd0: code = 6'b001011;
            2'd1: code = 6'b010101;
            2'd2: code = 6'b111000;
            default: code = 6'b100110;
        endcase
    endfunction
    localparam [5:0] ERROR = 6'b011110;

    // The lock without faults: 0 LOCKED, 1 CHECK, 2 OPEN, 3 LOCKOUT.
    reg [1:0] r_state = 0, r_fails = 0;
    wire [2:0] r_tried = {1'b0, r_fails} + 3'd1;
    always @(posedge clk) begin
        if (!rst_n) begin
            r_state <= 0;
            r_fails <= 0;
        end else if (r_state == 0) begin
            if (start) r_state <= 1;
        end else if (r_state == 1) begin
            if (key_ok) begin
                r_state <= 2;
                r_fails <= 0;
            end else begin
                r_fails <= r_tried[1:0];
                r_state <= r_tried >= MAX_TRIES ? 3 : 0;
            end
        end else if (r_state == 2) begin
            if (relock) r_state <= 0;
        end
    end

    wire [9:0] fault_w = {{(10 - FW){1'b0}}, fault};
    wire hit = rst_n && fault != 0;                 // a flip that takes effect at this edge
    reg f_past = 0, dirty = 0, last_hit = 0, used = 0, first_on_count = 0;
    reg [1:0] age = 0;                              // edges since the first flip, up to 2
    always @(posedge clk) begin
        f_past <= 1;
        last_hit <= hit;
        if (hit) used <= 1;
        if (!rst_n) begin
            dirty <= 0;
            age <= 0;
        end else if (dirty || hit) begin
            if (!dirty) first_on_count <= fault[FW-1:FW-SW] == 0;
            dirty <= 1;
            age <= age == 2'd2 ? 2'd2 : age + 2'd1;
        end
    end

    always @(posedge clk) begin
        if (!f_past) as_initial_reset: assume(!rst_n);
        as_fault_shape: assume(ones(fault_w) <= FAULT_BITS && (STATE_ONLY == 0 || fault[FW-SW-1:0] == 0));
        if (f_past) begin
            if (!dirty) ap_match: assert(grant == (r_state == 2) && busy == (r_state == 1) &&
                                         lockout == (r_state == 3) && !alarm && fails == r_fails);
            if (grant) ap_no_escalation: assert(r_state == 2);
            cp_recovered_open: cover(!dirty && grant && used);
            cp_lockout: cover(!dirty && lockout);
            cp_grant_removed: cover(dirty && age == 1 && r_state == 2 && !grant);
            cp_count_flip_detected: cover(dirty && age == 2 && alarm && first_on_count);
            cp_flip_in_error: cover(dirty && age == 2 && last_hit && !alarm && !grant);
        end
    end

    generate
        if (ESCALATION_ONLY == 0) begin : g_detect
            always @(posedge clk)
                if (f_past && dirty && age == 2) ap_detect: assert(alarm || last_hit);
        end
        if (PROOF_AIDS != 0 && HARDENED != 0) begin : g_aids
            wire [9:0] expected = {code(r_state), r_fails, ~r_fails};
            wire [9:0] diff = regs ^ expected;
            always @(posedge clk) begin
                if (f_past) begin
                    ai_age: assert(dirty == (age != 0));
                    if (!dirty) ai_clean: assert(diff == 0);
                    if (dirty && age == 1) ai_first: assert(diff != 0 && ones(diff) <= FAULT_BITS &&
                                                           (STATE_ONLY == 0 || diff[3:0] == 0));
                    if (dirty && age == 2) ai_after: assert(ones({4'b0000, regs[9:4] ^ ERROR}) <= (last_hit ? FAULT_BITS : 0));
                end
            end
        end
    endgenerate
endmodule
