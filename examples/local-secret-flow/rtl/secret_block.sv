// A small key block: a key register with a second copy, a dummy cipher (XOR), a scan chain,
// a debug read port, an error record and erase (zeroize).
//
// The key written with key_we is the secret. Which outputs may depend on it is a table in the
// README; the formal wrapper and the testbench check that table, the design only follows it.
// Reset is synchronous and active low. The lifecycle (lc_in: 0 development, 1 production) is
// sampled while reset is low and stays fixed until the next reset.
//
// MUTATION selects a deliberate leak for the checks to find:
//   1  production scan entry does not erase, so the key can be shifted out
//   2  the production debug mask covers only the upper half of the key
//   3  a refused debug read records the unmasked value in the error detail
//   4  erase clears the cipher copy of the key but leaves the read-back copy
//   5  "key loaded" is taken from the key value (nonzero) instead of from the write
module secret_block #(parameter KW = 8, MUTATION = 0) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire          lc_in,
    input  wire          key_we,
    input  wire [KW-1:0] key_wdata,
    input  wire          start,
    input  wire [KW-1:0] din,
    input  wire          zeroize,
    input  wire          dbg_req,
    input  wire [1:0]    dbg_addr,
    input  wire          err_clr,
    input  wire          scan_en,
    input  wire          scan_in,
    output wire [3:0]    status,
    output wire [KW-1:0] ct,
    output reg  [KW-1:0] dbg_rdata,
    output reg  [KW+1:0] err_info,
    output reg           scan_out
`ifdef FORMAL
    ,
    output wire [3*KW-1:0] f_secret
`endif
);
    localparam [1:0] E_NOKEY = 2'd1, E_DENIED = 2'd2;
    localparam [KW-1:0] LOW_HALF = {KW{1'b1}} >> (KW / 2);

    reg          lc_q, key_valid, ct_valid, scan_mode;
    reg [KW-1:0] key_q;    // used by the cipher
    reg [KW-1:0] key_sh;   // read-back copy for the development debug port
    reg [KW-1:0] ct_q;

    wire prod   = lc_q;
    wire key_ok = MUTATION == 5 ? |key_q : key_valid;
    // Entering scan in production erases first; nothing is shifted on that edge.
    wire entry_erase = scan_en && !scan_mode && prod && MUTATION != 1;
    wire denied = dbg_req && dbg_addr == 2'd1 && prod;

    assign status = {scan_mode, lc_q, ct_valid, key_ok};
    assign ct = ct_valid ? ct_q : {KW{1'b0}};
`ifdef FORMAL
    assign f_secret = {key_q, key_sh, ct_q};
`endif

    reg [KW-1:0] read_value;
    always @* begin
        case (dbg_addr)
            2'd0: read_value = {{(KW - 4){1'b0}}, status};
            2'd1: read_value = !prod ? key_sh : MUTATION == 2 ? key_sh & LOW_HALF : {KW{1'b0}};
            2'd2: read_value = ct;
            default: read_value = {{(KW - 2){1'b0}}, err_info[KW+1:KW]};
        endcase
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            lc_q <= lc_in;
            key_valid <= 1'b0;
            ct_valid <= 1'b0;
            scan_mode <= 1'b0;
            key_q <= {KW{1'b0}};
            key_sh <= {KW{1'b0}};
            ct_q <= {KW{1'b0}};
            dbg_rdata <= {KW{1'b0}};
            err_info <= {(KW + 2){1'b0}};
            scan_out <= 1'b0;
        end else if (zeroize) begin
            // Erase wins over everything else on this edge, including a read.
            key_valid <= 1'b0;
            ct_valid <= 1'b0;
            key_q <= {KW{1'b0}};
            if (MUTATION != 4) key_sh <= {KW{1'b0}};
            ct_q <= {KW{1'b0}};
            dbg_rdata <= {KW{1'b0}};
            scan_out <= 1'b0;
            scan_mode <= scan_en;
        end else begin
            dbg_rdata <= dbg_req && !entry_erase ? read_value : {KW{1'b0}};
            // An event wins over a clear on the same edge, so that it is not lost.
            if (denied)
                err_info <= {E_DENIED, MUTATION == 3 ? key_sh : {{(KW - 2){1'b0}}, dbg_addr}};
            else if (!scan_en && !key_we && start && !key_ok)
                err_info <= {E_NOKEY, {KW{1'b0}}};
            else if (err_clr)
                err_info <= {(KW + 2){1'b0}};
            if (scan_en) begin
                scan_mode <= 1'b1;
                if (entry_erase) begin
                    key_valid <= 1'b0;
                    ct_valid <= 1'b0;
                    key_q <= {KW{1'b0}};
                    key_sh <= {KW{1'b0}};
                    ct_q <= {KW{1'b0}};
                    scan_out <= 1'b0;
                end else begin
                    // The chain is {key_q, ct_q}; the read-back copy follows the cipher copy.
                    {key_q, ct_q} <= {key_q[KW-2:0], ct_q, scan_in};
                    key_sh <= {key_q[KW-2:0], ct_q[KW-1]};
                    scan_out <= key_q[KW-1];
                end
            end else begin
                scan_mode <= 1'b0;
                scan_out <= 1'b0;
                if (key_we) begin
                    key_q <= key_wdata;
                    key_sh <= key_wdata;
                    key_valid <= 1'b1;
                    ct_valid <= 1'b0;
                    ct_q <= {KW{1'b0}};
                end else if (start && key_ok) begin
                    ct_q <= din ^ key_q;
                    ct_valid <= 1'b1;
                end
            end
        end
    end
endmodule
