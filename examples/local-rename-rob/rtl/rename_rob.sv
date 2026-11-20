// Register renaming with a free list and a reorder buffer, one instruction per cycle.
//
// Each instruction writes one logical register. It gets a free physical register (the lowest
// one) and a place at the tail of the reorder buffer, which keeps the physical register that
// the logical register had before. Retirement, at the head and in order, frees that older
// register. A flush cancels everything younger than a given instruction by undoing the tail
// one entry per cycle. An instruction that completed with an exception is not retired: when
// it reaches the head, it and everything younger are undone the same way.
module rename_rob #(
    parameter MUTATION = 0,
    parameter LREGS = 4,   // logical registers
    parameter PREGS = 8,   // physical registers, more than LREGS
    parameter ROB = 4,     // reorder buffer entries, a power of two
    parameter DW = 8,
    parameter LW = $clog2(LREGS),
    parameter PW = $clog2(PREGS),
    parameter RW = $clog2(ROB)
) (
    input  wire              clk,
    input  wire              rst_n,       // synchronous, active low
    // allocate: one instruction that writes alloc_dst
    input  wire              alloc_valid,
    input  wire [LW-1:0]     alloc_dst,
    output wire              alloc_ready,
    output wire [RW-1:0]     alloc_tag,   // the place it gets in the reorder buffer
    // complete: the result of the instruction at done_tag, or its exception
    input  wire              done_valid,
    input  wire [RW-1:0]     done_tag,
    input  wire [DW-1:0]     done_value,
    input  wire              done_exc,
    // flush: cancel every instruction younger than the one at flush_tag
    input  wire              flush_valid,
    input  wire [RW-1:0]     flush_tag,
    output wire              flush_ready,
    // commit: with commit_en, the completed head retires or traps in this cycle
    input  wire              commit_en,
    output wire              retire_valid,
    output wire              trap_valid,
    output wire [RW-1:0]     retire_tag,
    output wire [LW-1:0]     retire_dst,
    output wire [DW-1:0]     retire_value,
    // committed state
    input  wire [LW-1:0]     rd_addr,
    output wire [DW-1:0]     rd_value,
    output reg               walking,     // undoing cancelled instructions
    output reg  [RW:0]       count,       // instructions in the reorder buffer
    // internal tables, for checkers only
    output wire [PREGS-1:0]    free_o,
    output wire [LREGS*PW-1:0] rmap_o,
    output wire [LREGS*PW-1:0] cmap_o,
    output wire [RW-1:0]       head_o,
    output wire [ROB*LW-1:0]   rob_dst_o,
    output wire [ROB*PW-1:0]   rob_new_o,
    output wire [ROB*PW-1:0]   rob_old_o
);
    reg [PREGS-1:0]    free;      // free list, one bit per physical register
    reg [LREGS*PW-1:0] rmap;      // newest mapping, used by allocation
    reg [LREGS*PW-1:0] cmap;      // mapping of the retired instructions
    reg [PREGS*DW-1:0] prf;       // values of the physical registers
    reg [RW-1:0]       head;
    reg [RW:0]         keep;      // a walk stops when count has come down to this
    reg [ROB*LW-1:0]   rob_dst;
    reg [ROB*PW-1:0]   rob_new;   // register the instruction writes
    reg [ROB*PW-1:0]   rob_old;   // register its logical register had before
    reg [ROB-1:0]      rob_done, rob_exc;

    assign free_o = free;
    assign rmap_o = rmap;
    assign cmap_o = cmap;
    assign head_o = head;
    assign rob_dst_o = rob_dst;
    assign rob_new_o = rob_new;
    assign rob_old_o = rob_old;

    // An entry is in use when its distance from the head is below count.
    wire [RW-1:0] tail = head + count[RW-1:0];
    wire [RW-1:0] last = tail - 1'b1;
    wire [RW-1:0] done_age = done_tag - head;
    wire [RW-1:0] flush_age = flush_tag - head;
    wire done_live = {1'b0, done_age} < count;
    wire flush_live = {1'b0, flush_age} < count;

    wire [LW-1:0] head_dst = rob_dst[head*LW +: LW];
    wire [PW-1:0] head_new = rob_new[head*PW +: PW];
    wire [PW-1:0] head_old = rob_old[head*PW +: PW];
    wire [LW-1:0] last_dst = rob_dst[last*LW +: LW];
    wire [PW-1:0] last_new = rob_new[last*PW +: PW];
    wire [PW-1:0] last_old = rob_old[last*PW +: PW];
    wire [PW-1:0] done_new = rob_new[done_tag*PW +: PW];

    // The lowest free physical register.
    reg [PW-1:0] pick;
    integer n;
    always @* begin
        pick = {PW{1'b0}};
        for (n = PREGS - 1; n >= 0; n = n - 1)
            if (free[n]) pick = n[PW-1:0];
    end

    wire flush_fire = flush_valid && !walking && flush_live;
    wire head_ready = commit_en && !walking && !flush_fire && count != 0 && rob_done[head];
    // Mutation 6: an exception at the head is retired like any other instruction.
    wire head_trap = rob_exc[head] && MUTATION != 6;
    assign retire_valid = head_ready && !head_trap;
    assign trap_valid = head_ready && head_trap;
    assign retire_tag = head;
    assign retire_dst = head_dst;
    assign retire_value = prf[head_new*DW +: DW];
    assign flush_ready = !walking;
    // Mutation 4: allocation does not look at the room that is left.
    wire room = (count < ROB[RW:0] && |free) || MUTATION == 4;
    assign alloc_ready = !walking && !flush_fire && !trap_valid && room;
    assign alloc_tag = tail;
    wire alloc_fire = alloc_valid && alloc_ready;
    assign rd_value = prf[cmap[rd_addr*PW +: PW]*DW +: DW];

    wire undo = walking && count > keep;
    wire [RW:0] flush_keep = {1'b0, flush_age} + {{RW{1'b0}}, MUTATION != 5};  // mutation 5: cancels flush_tag too

    integer i;
    always @(posedge clk) begin
        if (!rst_n) begin
            walking <= 1'b0; count <= {RW+1{1'b0}}; head <= {RW{1'b0}}; keep <= {RW+1{1'b0}};
            rob_done <= {ROB{1'b0}}; rob_exc <= {ROB{1'b0}};
            rob_dst <= {ROB*LW{1'b0}}; rob_new <= {ROB*PW{1'b0}}; rob_old <= {ROB*PW{1'b0}};
            prf <= {PREGS*DW{1'b0}};
            for (i = 0; i < LREGS; i = i + 1) begin
                rmap[i*PW +: PW] <= i[PW-1:0];
                cmap[i*PW +: PW] <= i[PW-1:0];
            end
            for (i = 0; i < PREGS; i = i + 1) free[i] <= i >= LREGS;
        end else begin
            // complete: once, and only for an entry that is in use
            if (done_valid && done_live && !rob_done[done_tag]) begin
                rob_done[done_tag] <= 1'b1;
                rob_exc[done_tag] <= done_exc;
                prf[done_new*DW +: DW] <= done_value;
            end
            if (undo) begin
                // Undo the youngest instruction: its logical register gets the older mapping
                // back and its own register returns to the free list.
                // Mutation 3: restores the committed mapping instead of the one before.
                rmap[last_dst*PW +: PW] <= MUTATION == 3 ? cmap[last_dst*PW +: PW] : last_old;
                if (MUTATION != 1) free[last_new] <= 1'b1;  // mutation 1: the register is lost
                count <= count - 1'b1;
            end else if (walking) begin
                walking <= 1'b0;
            end else if (flush_fire) begin
                walking <= 1'b1;
                keep <= flush_keep;
            end else begin
                if (trap_valid) begin
                    walking <= 1'b1;
                    keep <= {RW+1{1'b0}};
                end
                if (retire_valid) begin
                    cmap[head_dst*PW +: PW] <= head_new;
                    free[head_old] <= 1'b1;
                    // Mutation 2: also frees the register that was just committed.
                    if (MUTATION == 2) free[head_new] <= 1'b1;
                    head <= head + 1'b1;
                end
                if (alloc_fire) begin
                    rob_dst[tail*LW +: LW] <= alloc_dst;
                    rob_new[tail*PW +: PW] <= pick;
                    rob_old[tail*PW +: PW] <= rmap[alloc_dst*PW +: PW];
                    rob_done[tail] <= 1'b0;
                    rob_exc[tail] <= 1'b0;
                    rmap[alloc_dst*PW +: PW] <= pick;
                    free[pick] <= 1'b0;
                end
                count <= count + {{RW{1'b0}}, alloc_fire} - {{RW{1'b0}}, retire_valid};
            end
        end
    end

`ifdef FORMAL
    // One physical register, chosen freely and the same in every cycle, is followed. It is in
    // exactly one of three places: free, named by the newest mapping, or kept by an instruction
    // in the reorder buffer as the mapping it replaced. Seen another way, it has exactly one
    // owner: the free list, the committed mapping, or an instruction in the buffer.
    (* anyconst *) reg [PW-1:0] f_p;
    wire [RW-1:0] prev = last - 1'b1;
    reg [ROB-1:0] f_live;
    reg f_restore, f_chain, f_range, f_committed;
    reg [1:0] f_places, f_owners;
    reg [PW-1:0] f_expect;
    reg [RW-1:0] f_slot, f_other;
    integer l, a, b;
    always @* begin
        for (a = 0; a < ROB; a = a + 1) begin
            f_slot = a[RW-1:0] - head;
            f_live[a] = {1'b0, f_slot} < count;
        end
        f_places = {1'b0, free[f_p]}; f_owners = {1'b0, free[f_p]}; f_committed = 0;
        for (l = 0; l < LREGS; l = l + 1) begin
            if (rmap[l*PW +: PW] == f_p && f_places != 2'd3) f_places = f_places + 1'b1;
            if (cmap[l*PW +: PW] == f_p && f_owners != 2'd3) f_owners = f_owners + 1'b1;
            if (cmap[l*PW +: PW] == f_p) f_committed = 1;
        end
        for (a = 0; a < ROB; a = a + 1) begin
            if (f_live[a] && rob_old[a*PW +: PW] == f_p && f_places != 2'd3) f_places = f_places + 1'b1;
            if (f_live[a] && rob_new[a*PW +: PW] == f_p && f_owners != 2'd3) f_owners = f_owners + 1'b1;
        end
        // The newest mapping of a logical register is the register of the youngest instruction
        // in the buffer that writes it, or the committed mapping when there is none.
        f_restore = 1;
        for (l = 0; l < LREGS; l = l + 1) begin
            f_expect = cmap[l*PW +: PW];
            for (a = 0; a < ROB; a = a + 1) begin
                f_slot = head + a[RW-1:0];
                if (a < count && rob_dst[f_slot*LW +: LW] == l) f_expect = rob_new[f_slot*PW +: PW];
            end
            if (rmap[l*PW +: PW] != f_expect) f_restore = 0;
        end
        // The mapping an instruction replaced is the register of the nearest older instruction
        // that writes the same logical register, or the committed mapping.
        f_chain = 1; f_range = 1;
        for (a = 0; a < ROB; a = a + 1) begin
            f_slot = head + a[RW-1:0];
            f_expect = cmap[rob_dst[f_slot*LW +: LW]*PW +: PW];
            for (b = 0; b < ROB; b = b + 1) begin
                f_other = head + b[RW-1:0];
                if (b < a && rob_dst[f_other*LW +: LW] == rob_dst[f_slot*LW +: LW]) f_expect = rob_new[f_other*PW +: PW];
            end
            if (a < count) begin
                if (rob_old[f_slot*PW +: PW] != f_expect) f_chain = 0;
                if (rob_old[f_slot*PW +: PW] >= PREGS || rob_new[f_slot*PW +: PW] >= PREGS ||
                    rob_dst[f_slot*LW +: LW] >= LREGS) f_range = 0;
            end
        end
        for (l = 0; l < LREGS; l = l + 1)
            if (rmap[l*PW +: PW] >= PREGS || cmap[l*PW +: PW] >= PREGS) f_range = 0;
    end

    // One instruction, chosen freely: a flush that names it must leave it in the buffer.
    (* anyconst *) reg [RW-1:0] f_tag;
    wire [RW-1:0] f_tag_age = f_tag - head;
    wire f_tag_live = {1'b0, f_tag_age} < count;
    reg f_past = 0, f_protect = 0, f_walked = 0;
    // The value of the followed register in the cycle before, and whether it was committed then.
    reg [DW-1:0] f_before;
    reg f_before_committed = 0;
    always @(posedge clk) begin
        f_past <= 1;
        f_before <= prf[f_p*DW +: DW];
        f_before_committed <= rst_n && f_committed;
        if (!rst_n) begin f_protect <= 0; f_walked <= 0; end
        else begin
            if (flush_fire && flush_tag == f_tag) f_protect <= 1;
            else if (!walking) f_protect <= 0;
            if (undo) f_walked <= 1;
        end
    end

    always @(posedge clk) begin
        if (!f_past) as_initial_reset: assume(!rst_n);
        if (f_past) begin
            if (f_p < PREGS) ap_no_leak: assert(f_places != 0);
            ap_no_double: assert(f_places <= 1);
            if (f_p < PREGS) ap_owner: assert(f_owners == 1);
            ap_restore: assert(f_restore);
            if (alloc_valid && alloc_ready) ap_stall: assert(count < ROB && |free);
            if (retire_valid) ap_trap: assert(!rob_exc[head]);
            if (f_protect) ap_flush_keeps: assert(f_tag_live && (!walking || {1'b0, f_tag_age} < keep));
            // A register that stays committed keeps its value: completions never write it.
            if (f_before_committed && f_committed) ap_committed_stable: assert(prf[f_p*DW +: DW] == f_before);
            // Auxiliary invariants; with them the properties above are inductive.
            ai_chain: assert(f_chain);
            ai_range: assert(f_range);
            ai_count: assert(count <= ROB);
            cp_stall: cover(rst_n && alloc_valid && !walking && !flush_fire && !trap_valid && !alloc_ready);
            cp_retire_alloc: cover(rst_n && retire_valid && alloc_valid && alloc_ready);
            cp_undo_same: cover(rst_n && undo && count >= 2 && rob_dst[prev*LW +: LW] == last_dst);
            cp_trap_younger: cover(rst_n && trap_valid && count >= 2);
            cp_reuse: cover(rst_n && f_walked && alloc_valid && alloc_ready);
        end
    end
`endif
endmodule
