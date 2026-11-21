// Access lock whose state register and failure counter are hardened against bit flips.
//
//   LOCKED --start--> CHECK --key_ok--> OPEN --relock--> LOCKED
//                       |  wrong key: fails + 1, LOCKOUT at MAX_TRIES failures, else LOCKED
//   LOCKOUT keeps every request out until reset. OPEN is the only state with grant = 1.
//
// HARDENED = 1 stores the state in a 6-bit code whose valid words differ pairwise in at least
// three bits, and keeps a complement copy of the failure counter. A word that is not a valid
// code, or a counter that disagrees with its copy, sends the lock to ERROR at the next edge.
// ERROR raises alarm, grants nothing and is left only by reset. HARDENED = 0 is the same lock
// with a 3-bit binary state code and a single counter, kept for comparison.
//
// fault_xor is a verification hook: it is XORed into the stored registers after the normal
// update, {state, fails} and, when hardened, the complement copy as the two lowest bits.
// Reset wins over it. Tie it to zero in a design. f_regs exists only for the formal harness.
module hardened_lock #(parameter HARDENED = 1, MAX_TRIES = 3, MUTATION = 0) (
    input wire clk, rst_n, start, key_ok, relock,
    input wire [(HARDENED != 0 ? 10 : 5) - 1:0] fault_xor,
    output wire grant, busy, lockout, alarm,
    output wire [1:0] fails
`ifdef FORMAL
    , output wire [(HARDENED != 0 ? 10 : 5) - 1:0] f_regs
`endif
);
    localparam SW = HARDENED != 0 ? 6 : 3;   // state code width
    localparam FW = HARDENED != 0 ? 10 : 5;  // width of all stored bits
    localparam CB = HARDENED != 0 ? 2 : 0;   // position of the counter in fault_xor
    // Hardened codes. The four working states differ pairwise in four bits; ERROR differs
    // from each of them in three bits. Neither all zeros nor all ones is a valid code.
    localparam [5:0] H_LOCKED = MUTATION == 1 ? 6'b111001 : 6'b001011;   // 1: one bit from OPEN
    localparam [5:0] H_CHECK = 6'b010101;
    localparam [5:0] H_OPEN = 6'b111000;
    localparam [5:0] H_LOCKOUT = 6'b100110;
    localparam [5:0] H_ERROR = 6'b011110;
    localparam [5:0] B_LOCKED = 6'd0, B_CHECK = 6'd1, B_OPEN = 6'd2, B_LOCKOUT = 6'd3, B_ERROR = 6'd4;
    localparam [SW-1:0] C_LOCKED = HARDENED != 0 ? H_LOCKED[SW-1:0] : B_LOCKED[SW-1:0];
    localparam [SW-1:0] C_CHECK = HARDENED != 0 ? H_CHECK[SW-1:0] : B_CHECK[SW-1:0];
    localparam [SW-1:0] C_OPEN = HARDENED != 0 ? H_OPEN[SW-1:0] : B_OPEN[SW-1:0];
    localparam [SW-1:0] C_LOCKOUT = HARDENED != 0 ? H_LOCKOUT[SW-1:0] : B_LOCKOUT[SW-1:0];
    localparam [SW-1:0] C_ERROR = HARDENED != 0 ? H_ERROR[SW-1:0] : B_ERROR[SW-1:0];
    localparam [2:0] LIMIT = MAX_TRIES[2:0];   // MAX_TRIES is 1 to 3

    reg [SW-1:0] state_q;
    reg [1:0] cnt_q;
    wire [SW-1:0] flip_state = fault_xor[FW-1:FW-SW];
    wire [1:0] flip_cnt = fault_xor[CB+1:CB];
    wire valid = state_q == C_LOCKED || state_q == C_CHECK || state_q == C_OPEN ||
                 state_q == C_LOCKOUT || state_q == C_ERROR;
    wire cnt_ok;
    wire [2:0] tried = {1'b0, cnt_q} + 3'd1;

    reg [SW-1:0] n_state;
    reg [1:0] n_cnt;
    always @* begin
        n_state = state_q;
        n_cnt = cnt_q;
        if (!valid) n_state = MUTATION == 4 ? C_LOCKED : C_ERROR;   // 4: an unknown word restarts quietly
        else if (!cnt_ok) n_state = C_ERROR;
        else if (state_q == C_LOCKED) begin
            if (start) n_state = C_CHECK;
        end else if (state_q == C_CHECK) begin
            if (key_ok) begin
                n_state = C_OPEN;
                if (MUTATION != 7) n_cnt = 2'd0;   // 7: success keeps the failures
            end else begin
                n_cnt = tried[1:0];
                n_state = (MUTATION == 5 ? tried > LIMIT : tried >= LIMIT) ? C_LOCKOUT : C_LOCKED;
            end
        end else if (state_q == C_OPEN) begin
            if (relock) n_state = C_LOCKED;
        end else if (state_q == C_ERROR) begin
            if (MUTATION == 3 && relock) n_state = C_LOCKED;   // 3: relock leaves ERROR
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            state_q <= C_LOCKED;
            cnt_q <= 2'd0;
        end else begin
            state_q <= n_state ^ flip_state;
            cnt_q <= n_cnt ^ flip_cnt;
        end
    end

    generate
        if (HARDENED != 0) begin : g_copy
            reg [1:0] cntn_q;   // always the complement of cnt_q unless a bit flipped
            always @(posedge clk) begin
                if (!rst_n) cntn_q <= 2'b11;
                else cntn_q <= ~n_cnt ^ fault_xor[1:0];
            end
            // 2: the copy is never compared. 6: it is compared only while checking a key.
            assign cnt_ok = MUTATION == 2 ? 1'b1 :
                            MUTATION == 6 ? (state_q != C_CHECK || cnt_q == ~cntn_q) : cnt_q == ~cntn_q;
`ifdef FORMAL
            assign f_regs = {state_q, cnt_q, cntn_q};
`endif
        end else begin : g_plain
            assign cnt_ok = 1'b1;
`ifdef FORMAL
            assign f_regs = {state_q, cnt_q};
`endif
        end
    endgenerate

    // 8: privilege decoded as "none of the other states", so an unknown word grants.
    assign grant = MUTATION == 8 ? state_q != C_LOCKED && state_q != C_CHECK && state_q != C_LOCKOUT &&
                                   state_q != C_ERROR : state_q == C_OPEN;
    assign busy = state_q == C_CHECK;
    assign lockout = state_q == C_LOCKOUT;
    assign alarm = state_q == C_ERROR;
    assign fails = cnt_q;
endmodule
