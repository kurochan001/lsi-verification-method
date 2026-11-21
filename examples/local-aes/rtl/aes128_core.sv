// AES-128 encryption, one round per clock, with a fixed latency and zeroization.
// Teaching model: digital cycle behaviour only; power and electromagnetic side channels are out of scope.
//
// Byte i of a 128-bit value is bits [127-8*i -: 8]; byte 4*c+r is row r of column c (FIPS 197 order).
// Accepting start (ready=1) loads block^key and the key. Ten busy clocks follow (progress 1..10), one
// round each, with the round key derived on the fly. The result is then held in out_valid until
// out_ready. Abort and reset clear the state, the round key and the round constant. The round key is
// also cleared at the end of the last round and the state when the result is taken, so an idle core
// holds no data. out_block is 0 whenever out_valid is 0.
//
// MUTATION (deliberate faults for the regression):
//   1 an all-zero block finishes after five rounds (data-dependent timing)
//   2 cancel leaves the round key        3 reset leaves the state
//   4 out_block shows the state while busy
//   5 one S-box entry is wrong          6 ShiftRows rotates the wrong way
//   7 one MixColumns coefficient is 1 instead of 3
//   8 the round constant is doubled without reduction (wrong from round 9)
//   9 the last round keeps MixColumns
module aes128_core #(parameter MUTATION = 0) (
    input  wire         clk,
    input  wire         rst_n,
    input  wire         start,
    input  wire         cancel,
    input  wire [127:0] key,
    input  wire [127:0] block,
    input  wire         out_ready,
    output wire         ready,
    output wire         busy,
    output reg          out_valid,
    output wire [3:0]   progress,
    output wire [127:0] out_block
);
    reg [127:0] state;
    reg [127:0] rkey;
    reg [7:0]   rcon;
    reg [3:0]   round;

    function automatic [7:0] xtime(input [7:0] a);
        xtime = {a[6:0], 1'b0} ^ (a[7] ? 8'h1b : 8'h00);
    endfunction

    function automatic [7:0] gmul(input [7:0] a, input [7:0] b);
        reg [7:0] p, x;
        integer i;
        begin
            p = 8'h00;
            x = a;
            for (i = 0; i < 8; i = i + 1) begin
                if (b[i]) p = p ^ x;
                x = xtime(x);
            end
            gmul = p;
        end
    endfunction

    // Inverse as a^254 = a^2 * a^4 * ... * a^128 (0 maps to 0), then the affine map.
    function automatic [7:0] sbox(input [7:0] a);
        reg [7:0] power, inv;
        integer i;
        begin
            power = a;
            inv = 8'h01;
            for (i = 1; i < 8; i = i + 1) begin
                power = gmul(power, power);
                inv = gmul(inv, power);
            end
            sbox = inv ^ {inv[6:0], inv[7]} ^ {inv[5:0], inv[7:6]} ^ {inv[4:0], inv[7:5]} ^
                   {inv[3:0], inv[7:4]} ^ 8'h63;
            if (MUTATION == 5 && a == 8'h53) sbox = 8'hec;
        end
    endfunction

    function automatic [7:0] get(input [127:0] v, input integer i);
        get = v[127 - 8 * i -: 8];
    endfunction

    function automatic [127:0] sub_shift(input [127:0] s);
        integer r, c, from;
        begin
            sub_shift = 128'h0;
            for (c = 0; c < 4; c = c + 1)
                for (r = 0; r < 4; r = r + 1) begin
                    from = MUTATION == 6 ? 4 * ((c - r + 4) % 4) + r : 4 * ((c + r) % 4) + r;
                    sub_shift[127 - 8 * (4 * c + r) -: 8] = sbox(get(s, from));
                end
        end
    endfunction

    function automatic [31:0] mix_column(input [31:0] w);
        reg [7:0] a0, a1, a2, a3;
        begin
            {a0, a1, a2, a3} = w;
            mix_column[31:24] = xtime(a0) ^ (MUTATION == 7 ? a1 : xtime(a1) ^ a1) ^ a2 ^ a3;
            mix_column[23:16] = a0 ^ xtime(a1) ^ xtime(a2) ^ a2 ^ a3;
            mix_column[15:8]  = a0 ^ a1 ^ xtime(a2) ^ xtime(a3) ^ a3;
            mix_column[7:0]   = xtime(a0) ^ a0 ^ a1 ^ a2 ^ xtime(a3);
        end
    endfunction

    wire last = round == 4'd10;
    wire [31:0] w3 = rkey[31:0];
    wire [31:0] sub_rot = {sbox(w3[23:16]), sbox(w3[15:8]), sbox(w3[7:0]), sbox(w3[31:24])};
    wire [31:0] n0 = rkey[127:96] ^ sub_rot ^ {rcon, 24'h0};
    wire [31:0] n1 = rkey[95:64] ^ n0;
    wire [31:0] n2 = rkey[63:32] ^ n1;
    wire [31:0] n3 = rkey[31:0] ^ n2;
    wire [127:0] next_key = {n0, n1, n2, n3};
    wire [127:0] shifted = sub_shift(state);
    wire [127:0] mixed = {mix_column(shifted[127:96]), mix_column(shifted[95:64]),
                          mix_column(shifted[63:32]), mix_column(shifted[31:0])};
    wire [127:0] round_out = ((last && MUTATION != 9) ? shifted : mixed) ^ next_key;
    wire [7:0] next_rcon = MUTATION == 8 ? {rcon[6:0], 1'b0} : xtime(rcon);
`ifdef FORMAL
    // The proofs replace the round function and the key schedule by free values on every clock.
    // The control and the clearing must then hold for any data path, which is a stronger claim than
    // for the real one. Ciphertext values are left to the simulation.
    (* anyseq *) wire [127:0] f_round_out;
    (* anyseq *) wire [127:0] f_next_key;
    wire [127:0] state_next = f_round_out;
    wire [127:0] key_next = f_next_key;
`else
    wire [127:0] state_next = round_out;
    wire [127:0] key_next = next_key;
`endif

    assign busy = round != 4'd0;
    assign ready = !busy && !out_valid;
    assign progress = round;
    assign out_block = (out_valid || MUTATION == 4) ? state : 128'h0;

    always @(posedge clk) begin
        if (!rst_n) begin
            round <= 4'd0;
            out_valid <= 1'b0;
            rkey <= 128'h0;
            rcon <= 8'h00;
            if (MUTATION != 3) state <= 128'h0;
        end else if (cancel) begin
            round <= 4'd0;
            out_valid <= 1'b0;
            state <= 128'h0;
            rcon <= 8'h00;
            if (MUTATION != 2) rkey <= 128'h0;
        end else if (out_valid) begin
            if (out_ready) begin
                out_valid <= 1'b0;
                state <= 128'h0;
            end
        end else if (!busy) begin
            if (start) begin
                state <= block ^ key;
                rkey <= key;
                rcon <= 8'h01;
                round <= (MUTATION == 1 && block == 128'h0) ? 4'd6 : 4'd1;
            end
        end else begin
            state <= state_next;
            if (last) begin
                round <= 4'd0;
                rkey <= 128'h0;
                rcon <= 8'h00;
                out_valid <= 1'b1;
            end else begin
                round <= round + 4'd1;
                rkey <= key_next;
                rcon <= next_rcon;
            end
        end
    end

`ifdef FORMAL
    // Invariants for the self-composition proof in aes_ct_formal.sv. Checked from the second
    // cycle on: the harness holds reset in the first one.
    reg f_past = 1'b0;
    always @(posedge clk) begin
        f_past <= 1'b1;
        if (f_past) begin
            ai_round: assert(round <= 4'd10);
            ai_idle_clear: assert(busy || out_valid || (state == 128'h0 && rkey == 128'h0 && rcon == 8'h00));
            ai_valid_clear: assert(!out_valid || (round == 4'd0 && rkey == 128'h0 && rcon == 8'h00));
            ai_gate: assert(out_valid || out_block == 128'h0);
        end
    end
`endif
endmodule
