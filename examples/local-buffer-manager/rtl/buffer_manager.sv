// A buffer manager: NB buffers, NQ queues, one shared next-pointer table.
//
// The free list and every queue are singly linked lists through the same table nxt[], each with
// a head, a tail and a count. A buffer taken out of a queue is held by its reader until it is
// released. So each buffer is in exactly one place: the free list, one queue, or held.
//
// In one cycle the design can take three operations at once, all of them seeing the state at the
// start of the cycle:
//   enqueue  (enq_valid, enq_q):  the head of the free list is appended to queue enq_q;
//                                 refused when the free list is empty.
//   dequeue  (deq_valid, deq_q):  the head of queue deq_q is taken out and becomes held;
//                                 refused when the queue is empty.
//   release  (rel_valid, rel_id): a held buffer is appended to the free list; a buffer that is
//                                 not held (free, or in a queue) is refused and nothing changes.
// A buffer released in a cycle is not given out by an enqueue of the same cycle, and a buffer
// dequeued in a cycle cannot be released in the same cycle.
module buffer_manager #(
    parameter MUTATION = 0,
    parameter NB = 16,            // buffers, a power of two
    parameter NQ = 4,             // queues, a power of two, at least 2
    parameter BW = $clog2(NB),
    parameter QW = $clog2(NQ)
) (
    input  wire              clk,
    input  wire              rst_n,       // synchronous, active low
    input  wire              enq_valid,
    input  wire [QW-1:0]     enq_q,
    output wire              enq_ready,
    output wire [BW-1:0]     enq_id,      // the buffer the enqueue takes
    input  wire              deq_valid,
    input  wire [QW-1:0]     deq_q,
    output wire              deq_ready,
    output wire [BW-1:0]     deq_id,      // the buffer the dequeue hands out
    input  wire              rel_valid,
    input  wire [BW-1:0]     rel_id,
    output wire              rel_ready,   // the buffer is held, so the release is taken
    output wire [BW:0]       free_count,
    output wire [NQ*(BW+1)-1:0] q_count_o,
    // internal tables, for checkers only
    output wire [NB*BW-1:0]  next_o,
    output wire [BW-1:0]     free_head_o,
    output wire [BW-1:0]     free_tail_o,
    output wire [NQ*BW-1:0]  q_head_o,
    output wire [NQ*BW-1:0]  q_tail_o,
    output wire [NB-1:0]     held_o
);
    reg [NB*BW-1:0]     nxt;
    reg [BW-1:0]        fhead, ftail;
    reg [BW:0]          fcnt;
    reg [NQ*BW-1:0]     qhead, qtail;
    reg [NQ*(BW+1)-1:0] qcnt;
    reg [NB-1:0]        held;

    assign next_o = nxt;
    assign free_head_o = fhead;
    assign free_tail_o = ftail;
    assign q_head_o = qhead;
    assign q_tail_o = qtail;
    assign q_count_o = qcnt;
    assign held_o = held;
    assign free_count = fcnt;

    wire [BW:0]   enq_cnt  = qcnt[enq_q*(BW+1) +: BW+1];
    wire [BW-1:0] enq_tail = qtail[enq_q*BW +: BW];
    wire [BW:0]   deq_cnt  = qcnt[deq_q*(BW+1) +: BW+1];
    wire [BW-1:0] deq_head = qhead[deq_q*BW +: BW];

    // Mutation 6: an enqueue is taken although the free list is empty.
    assign enq_ready = fcnt != 0 || MUTATION == 6;
    assign enq_id = fhead;
    // Mutation 5: a dequeue is taken from an empty queue.
    assign deq_ready = deq_cnt != 0 || MUTATION == 5;
    assign deq_id = deq_head;
    // Mutation 2: a release is taken for a buffer that is not held (a double free).
    assign rel_ready = held[rel_id] || MUTATION == 2;

    wire enq_fire = enq_valid && enq_ready;
    wire deq_fire = deq_valid && deq_ready;
    wire rel_fire = rel_valid && rel_ready;
    wire same = enq_fire && deq_fire && enq_q == deq_q;

    integer i, q;
    always @(posedge clk) begin
        if (!rst_n) begin
            // Every buffer is free, linked in order 0, 1, ..., NB-1.
            for (i = 0; i < NB; i = i + 1) nxt[i*BW +: BW] <= i[BW-1:0] + 1'b1;
            fhead <= {BW{1'b0}};
            ftail <= NB[BW-1:0] - 1'b1;
            fcnt <= NB[BW:0];
            qhead <= {NQ*BW{1'b0}};
            qtail <= {NQ*BW{1'b0}};
            qcnt <= {NQ*(BW+1){1'b0}};
            held <= {NB{1'b0}};
        end else begin
            // The free list: the head leaves with an enqueue, a released buffer joins at the tail.
            if (rel_fire && MUTATION != 1) begin   // mutation 1: a released buffer is never linked again
                if (fcnt == 0 || (enq_fire && fcnt == 1)) begin
                    // The list is empty after this cycle's removal: the buffer becomes head and tail.
                    // Mutation 7: the head is moved on as if the list stayed nonempty.
                    fhead <= (MUTATION == 7 && enq_fire) ? nxt[fhead*BW +: BW] : rel_id;
                    if (MUTATION == 7 && enq_fire) nxt[ftail*BW +: BW] <= rel_id;
                end else begin
                    if (enq_fire) fhead <= nxt[fhead*BW +: BW];
                    nxt[ftail*BW +: BW] <= rel_id;
                end
                ftail <= rel_id;
            end else if (enq_fire) begin
                fhead <= nxt[fhead*BW +: BW];
            end
            fcnt <= fcnt - {{BW{1'b0}}, enq_fire} + {{BW{1'b0}}, rel_fire && MUTATION != 1};

            for (q = 0; q < NQ; q = q + 1) begin
                if (same && q[QW-1:0] == enq_q) begin
                    // Out at the head and in at the tail of the same queue.
                    if (enq_cnt == 1) begin
                        // The only buffer leaves: the new one is head and tail.
                        // Mutation 4: the head is moved to the next of the buffer that left.
                        qhead[q*BW +: BW] <= MUTATION == 4 ? nxt[deq_head*BW +: BW] : fhead;
                    end else begin
                        qhead[q*BW +: BW] <= nxt[deq_head*BW +: BW];
                        nxt[enq_tail*BW +: BW] <= fhead;
                    end
                    qtail[q*BW +: BW] <= fhead;
                end else begin
                    if (deq_fire && q[QW-1:0] == deq_q)
                        qhead[q*BW +: BW] <= nxt[deq_head*BW +: BW];
                    if (enq_fire && q[QW-1:0] == enq_q) begin
                        if (enq_cnt == 0)
                            qhead[q*BW +: BW] <= fhead;
                        else if (MUTATION != 3)   // mutation 3: the old tail is not linked to the new buffer
                            nxt[enq_tail*BW +: BW] <= fhead;
                        qtail[q*BW +: BW] <= fhead;
                    end
                end
                qcnt[q*(BW+1) +: BW+1] <= qcnt[q*(BW+1) +: BW+1]
                    + {{BW{1'b0}}, enq_fire && q[QW-1:0] == enq_q} - {{BW{1'b0}}, deq_fire && q[QW-1:0] == deq_q};
            end

            if (deq_fire) held[deq_head] <= 1'b1;
            if (rel_fire) held[rel_id] <= 1'b0;
        end
    end

`ifdef FORMAL
    // Walk every list from its head for as many steps as its count. List 0 is the free list and
    // list 1+q is queue q. f_seen marks the buffers each list meets, f_dup tells that a list met
    // a buffer twice, and f_last is the buffer met at the last step.
    localparam NL = NQ + 1;
    (* anyconst *) reg [BW-1:0] f_b;   // one buffer, chosen freely, the same in every cycle
    reg [NL*NB-1:0] f_seen;
    reg [NL*BW-1:0] f_last;
    reg [NL-1:0]    f_dup;
    reg [3:0]       f_places;          // places of f_b, counted with multiplicity
    reg [NB-1:0]    f_mask, f_union;
    reg [BW-1:0]    f_p, f_head_l, f_tail_l;
    reg [BW:0]      f_n;
    reg [BW+3:0]    f_total;
    reg             f_tails, f_disjoint, f_counts_ok;
    integer l, s, b;
    always @* begin
        f_places = {3'b0, held[f_b]};
        f_tails = 1'b1;
        f_disjoint = 1'b1;
        f_union = held;
        f_counts_ok = fcnt <= NB;
        f_total = {3'b0, fcnt};
        for (b = 0; b < NB; b = b + 1) f_total = f_total + {{BW+3{1'b0}}, held[b]};
        for (l = 0; l < NL; l = l + 1) begin
            f_head_l = l == 0 ? fhead : qhead[(l - 1)*BW +: BW];
            f_tail_l = l == 0 ? ftail : qtail[(l - 1)*BW +: BW];
            f_n = l == 0 ? fcnt : qcnt[(l - 1)*(BW+1) +: BW+1];
            if (l > 0) begin
                f_total = f_total + {3'b0, f_n};
                if (f_n > NB) f_counts_ok = 1'b0;
            end
            f_mask = {NB{1'b0}};
            f_dup[l] = 1'b0;
            f_p = f_head_l;
            f_last[l*BW +: BW] = f_head_l;
            for (s = 0; s < NB; s = s + 1) begin
                if (s < f_n) begin
                    if (f_mask[f_p]) f_dup[l] = 1'b1;
                    if (f_p == f_b && f_places != 4'hf) f_places = f_places + 1'b1;
                    f_mask[f_p] = 1'b1;
                    f_last[l*BW +: BW] = f_p;
                    f_p = nxt[f_p*BW +: BW];
                end
            end
            f_seen[l*NB +: NB] = f_mask;
            if (f_n != 0 && f_last[l*BW +: BW] != f_tail_l) f_tails = 1'b0;
            if (|(f_union & f_mask)) f_disjoint = 1'b0;
            f_union = f_union | f_mask;
        end
        if (f_total != NB) f_counts_ok = 1'b0;
    end

    reg f_past = 1'b0;
    always @(posedge clk) f_past <= 1'b1;

    always @(posedge clk) begin
        if (!f_past) as_initial_reset: assume(!rst_n);
        if (f_past) begin
            // The followed buffer is in exactly one place: free, in one queue, or held.
            ap_no_leak: assert(f_places != 0);
            ap_no_double: assert(f_places <= 1);
            // Every nonempty list ends where its tail says.
            ap_tail: assert(f_tails);
            // Operations are taken only when they may be.
            if (rel_valid && rel_ready) ap_release_held: assert(held[rel_id]);
            if (deq_valid && deq_ready) ap_deq_nonempty: assert(deq_cnt != 0);
            if (enq_valid && enq_ready) ap_enq_room: assert(fcnt != 0);
            // Auxiliary invariants about all buffers. The properties of the followed buffer alone
            // are not inductive: another buffer may be broken in a state that cannot be reached.
            ai_distinct: assert(f_dup == {NL{1'b0}});
            ai_disjoint: assert(f_disjoint);
            ai_cover: assert(&f_union);
            ai_counts: assert(f_counts_ok);
            cp_full: cover(rst_n && enq_valid && !enq_ready);
            cp_same_one: cover(rst_n && same && enq_cnt == 1);
            cp_free_swap: cover(rst_n && enq_fire && rel_fire && fcnt == 1);
            cp_refused_release: cover(rst_n && rel_valid && !rel_ready);
            cp_three: cover(rst_n && enq_fire && deq_fire && rel_fire && enq_q != deq_q);
        end
    end
`endif
endmodule
