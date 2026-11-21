// Self-composition: two copies of secret_block share every input except the written key.
// Each check says that an output is the same in both copies, unless the policy table in the
// README lets that output depend on the key in the current state. A difference where the table
// says "public" is a flow of the key to that output.
//
// AUX       = 1 adds the auxiliary invariants that the induction needs (all proved as asserts).
// INTERNAL  = 1 adds the check on the erased internal registers, not only on the outputs.
// PROD_ONLY = 1 assumes the production lifecycle at every reset.
// The detection tasks use AUX = 0 so that a counterexample names only the property it breaks.
module secret_flow_formal #(
    parameter KW = 8,
    parameter MUTATION = 0,
    parameter AUX = 1,
    parameter INTERNAL = 1,
    parameter PROD_ONLY = 0
) (
    input wire          clk,
    input wire          rst_n,
    input wire          lc_in,
    input wire          key_we,
    input wire [KW-1:0] key0,
    input wire [KW-1:0] key1,
    input wire          start,
    input wire [KW-1:0] din,
    input wire          zeroize,
    input wire          dbg_req,
    input wire [1:0]    dbg_addr,
    input wire          err_clr,
    input wire          scan_en,
    input wire          scan_in
);
    wire [3:0]      st0, st1;
    wire [KW-1:0]   ct0, ct1, rd0, rd1;
    wire [KW+1:0]   er0, er1;
    wire            so0, so1;
    wire [3*KW-1:0] fs0, fs1;

    secret_block #(.KW(KW), .MUTATION(MUTATION)) a(
        .clk(clk), .rst_n(rst_n), .lc_in(lc_in), .key_we(key_we), .key_wdata(key0), .start(start), .din(din),
        .zeroize(zeroize), .dbg_req(dbg_req), .dbg_addr(dbg_addr), .err_clr(err_clr), .scan_en(scan_en),
        .scan_in(scan_in), .status(st0), .ct(ct0), .dbg_rdata(rd0), .err_info(er0), .scan_out(so0), .f_secret(fs0));
    secret_block #(.KW(KW), .MUTATION(MUTATION)) b(
        .clk(clk), .rst_n(rst_n), .lc_in(lc_in), .key_we(key_we), .key_wdata(key1), .start(start), .din(din),
        .zeroize(zeroize), .dbg_req(dbg_req), .dbg_addr(dbg_addr), .err_clr(err_clr), .scan_en(scan_en),
        .scan_in(scan_in), .status(st1), .ct(ct1), .dbg_rdata(rd1), .err_info(er1), .scan_out(so1), .f_secret(fs1));

    // Public state, read from copy a. ap_status makes it the same in copy b.
    wire prod = st0[2], scan_mode = st0[3], ct_valid = st0[1], key_valid = st0[0];

    // allow: the read that produced the present dbg_rdata was one the table lets depend on the
    //        key (a development key read, or a result read while the result is valid).
    // clean: no key has been written since the last reset, erase or production scan entry.
    // had_key: a key was written since the last reset (for a cover only).
    reg past_valid = 1'b0, allow = 1'b0, clean = 1'b1, had_key = 1'b0;
    always @(posedge clk) begin
        past_valid <= 1'b1;
        if (!rst_n) had_key <= 1'b0;
        else if (key_we && !zeroize && !scan_en) had_key <= 1'b1;
        allow <= rst_n && !zeroize && dbg_req && ((dbg_addr == 2'd1 && !prod) || (dbg_addr == 2'd2 && ct_valid));
        if (!rst_n || zeroize || (scan_en && !scan_mode && prod)) clean <= 1'b1;
        else if (key_we && !scan_en) clean <= 1'b0;
    end

    always @(posedge clk) begin
        if (!past_valid) as_initial_reset: assume(!rst_n);
        if (past_valid) begin
            ap_status: assert(st0 == st1);
            if (prod) ap_scan: assert(so0 == so1);
            if (!allow) ap_dbg: assert(rd0 == rd1);
            ap_err: assert(er0 == er1);
            if (!ct_valid) ap_ct: assert(ct0 == ct1);
            // After an erase nothing may show the old key, even where the table otherwise allows it.
            if (clean) ap_erased: assert(ct0 == ct1 && rd0 == rd1 && so0 == so1);

            cp_ct_differs: cover(ct_valid && ct0 != ct1);
            cp_prod_ct_read: cover(prod && allow && rd0 != rd1);
            cp_dev_key_read: cover(!prod && allow && rd0 != rd1);
            cp_dev_scan_differs: cover(!prod && so0 != so1);
            cp_prod_denied: cover(prod && er0[KW+1:KW] == 2'd2);
            cp_no_key: cover(er0[KW+1:KW] == 2'd1);
            cp_prod_scan_shift: cover(prod && scan_mode && $past(prod && scan_mode));
            cp_erased_dev_read: cover(clean && had_key && !prod && allow);
        end
    end

    generate
        if (INTERNAL) begin : g_internal
            always @(posedge clk)
                if (past_valid && clean) ap_erased_internal: assert(fs0 == fs1);
        end
        if (AUX) begin : g_aux
            always @(posedge clk)
                if (past_valid) begin
                    // The two copies of the key agree in each design.
                    ai_copies: assert(fs0[3*KW-1:2*KW] == fs0[2*KW-1:KW] && fs1[3*KW-1:2*KW] == fs1[2*KW-1:KW]);
                    if (clean) ai_clean_idle: assert(!key_valid && !ct_valid);
                    if (clean) ai_clean_secret: assert(fs0 == fs1);
                    if (prod && scan_mode) ai_prod_scan: assert(clean);
                end
        end
        if (PROD_ONLY) begin : g_prod
            always @(posedge clk)
                if (!rst_n) as_prod: assume(lc_in);
        end
    endgenerate
endmodule
