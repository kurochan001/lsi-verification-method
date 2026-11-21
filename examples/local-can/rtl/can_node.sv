// CAN 2.0A (standard frame) controller for teaching: one transmit buffer, one receive output,
// bit timing with hard synchronisation and resynchronisation, error signalling and fault confinement.
// One time quantum is one clock. A bit is 1 + TSEG1 + TSEG2 quanta and is sampled after TSEG1.
// Level 0 is dominant. Overload frames are sent only as a reaction, never requested.
// MUTATION selects a deliberate fault for the regression; 0 is the correct design.
module can_node #(
    parameter integer TSEG1 = 13,
    parameter integer TSEG2 = 6,
    parameter integer SJW = 4,
    parameter integer MUTATION = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        can_rx,
    output reg         can_tx,
    input  wire        tx_valid,
    output wire        tx_ready,
    input  wire [10:0] tx_id,
    input  wire        tx_rtr,
    input  wire [3:0]  tx_dlc,
    input  wire [63:0] tx_data,      // first byte in bits 63..56
    output reg         tx_done,
    output reg         rx_valid,
    output reg  [10:0] rx_id,
    output reg         rx_rtr,
    output reg  [3:0]  rx_dlc,
    output reg  [63:0] rx_data,
    output reg         err_valid,
    output reg  [2:0]  err_code,     // 1 bit, 2 stuff, 3 CRC, 4 form, 5 ACK, 6 overload condition
    output reg         arb_lost,
    output reg  [1:0]  sync_kind,    // 1 hard synchronisation, 2 bit lengthened, 3 bit shortened
    output wire [8:0]  tec,
    output wire [7:0]  rec,
    output wire [1:0]  mode          // 0 error active, 1 error passive, 2 bus off
);
    localparam [3:0] INTEG = 4'd0, IDLE = 4'd1, BODY = 4'd2, TAIL = 4'd3, CRCDEL = 4'd4, ACK = 4'd5,
                     ACKDEL = 4'd6, EOFS = 4'd7, IFS = 4'd8, SUSP = 4'd9, FLAG = 4'd10, WAITR = 4'd11,
                     DELIM = 4'd12, OFF = 4'd13;
    localparam [1:0] F_ACTIVE = 2'd0, F_PASSIVE = 2'd1, F_OVERLOAD = 2'd2;
    localparam [2:0] E_BIT = 3'd1, E_STUFF = 3'd2, E_CRC = 3'd3, E_FORM = 3'd4, E_ACK = 3'd5, E_OVERLOAD = 3'd6;
    localparam [5:0] SAMPLE_AT = TSEG1[5:0];
    localparam [5:0] LAST = TSEG1[5:0] + TSEG2[5:0];
    localparam [5:0] JUMP = SJW[5:0];
    localparam [14:0] POLY = MUTATION == 2 ? 15'h4598 : 15'h4599;
    localparam [2:0] TX_STUFF_AT = MUTATION == 1 ? 3'd6 : 3'd5;

    // ---------------------------------------------------------------- transmit buffer
    reg        pend;
    reg [10:0] b_id;
    reg        b_rtr;
    reg [3:0]  b_dlc;
    reg [63:0] b_data;
    assign tx_ready = !pend;

    // ---------------------------------------------------------------- protocol state
    reg [3:0]  state;
    reg        role_tx, was_tx;
    reg [7:0]  n;                  // destuffed bits of the frame taken so far, SOF included
    reg        run_val;
    reg [2:0]  run_len;
    reg [14:0] crc;
    reg        crc_ok;
    reg [10:0] r_id;
    reg        r_rtr;
    reg [3:0]  r_dlc;
    reg [63:0] r_data;
    reg [3:0]  cnt;                // field counter: EOF, intermission, suspend, flag, delimiter, 11 recessive bits
    reg [7:0]  seq;                // completed sequences of 11 recessive bits while bus off
    reg [1:0]  flag_kind;
    reg [2:0]  equal;
    reg        prev_bit, first_after, ack_hold;
    reg [8:0]  tec_q;
    reg [7:0]  rec_q;

    assign tec = tec_q;
    assign rec = rec_q;
    wire passive = tec_q >= 9'd128 || rec_q >= 8'd128;
    assign mode = state == OFF ? 2'd2 : {1'b0, passive};

    wire [3:0] r_bytes = r_rtr ? 4'd0 : (r_dlc > 4'd8 ? 4'd8 : r_dlc);
    wire [3:0] b_bytes = b_rtr ? 4'd0 : (b_dlc > 4'd8 ? 4'd8 : b_dlc);
    wire [7:0] r_len = 8'd34 + {1'b0, r_bytes, 3'b000};          // SOF to the last CRC bit
    wire [7:0] b_crc_at = 8'd19 + {1'b0, b_bytes, 3'b000};
    wire [5:0] data_index = n[5:0] - 6'd19;                      // the differences below are taken modulo their width
    wire [3:0] crc_index = n[3:0] - (r_len[3:0] - 4'd15);
    wire [3:0] b_crc_index = n[3:0] - b_crc_at[3:0];

    // The bit a transmitter puts on the bus for destuffed position n.
    reg frame_bit;
    always @* begin
        if (n == 8'd0) frame_bit = 1'b0;
        else if (n <= 8'd11) frame_bit = b_id[4'd11 - n[3:0]];
        else if (n == 8'd12) frame_bit = b_rtr;
        else if (n <= 8'd14) frame_bit = 1'b0;
        else if (n <= 8'd18) frame_bit = b_dlc[2'd3 - (n[1:0] + 2'd1)];
        else if (n < b_crc_at) frame_bit = b_data[6'd63 - data_index];
        else frame_bit = crc[4'd14 - b_crc_index];
    end

    reg tx_now;
    always @* begin
        tx_now = 1'b1;
        case (state)
            IDLE: tx_now = !pend;
            BODY: if (role_tx) tx_now = run_len == TX_STUFF_AT ? !run_val : frame_bit;
            TAIL: if (role_tx) tx_now = !run_val;
            ACK: if (!role_tx && (crc_ok || MUTATION == 3)) tx_now = 1'b0;
            FLAG: if (flag_kind != F_PASSIVE) tx_now = 1'b0;
            default: tx_now = 1'b1;
        endcase
    end

    // ---------------------------------------------------------------- bit timing
    reg       rx_m, rx_s, rx_q, sampled, synced;
    reg [5:0] phase;               // quantum of the present bit: 0 is the synchronisation segment
    wire edge_rd = rx_q && !rx_s;
    wire hard_ok = state == IDLE || state == SUSP || (state == IFS && cnt == 4'd2);
    wire use_edge = edge_rd && !synced && sampled;
    wire hsync = use_edge && hard_ok;
    wire resync = use_edge && !hard_ok && MUTATION != 8 && state != OFF && state != INTEG;
    wire lag = resync && phase != 6'd0 && phase <= SAMPLE_AT && can_tx;   // own dominant edges are not followed
    wire lead = resync && phase > SAMPLE_AT;
    wire [5:0] behind = phase < JUMP ? phase : JUMP;
    wire [5:0] ahead = LAST + 6'd1 - phase;
    wire restart = hsync || (lead && ahead <= JUMP);
    wire sample_now = phase == SAMPLE_AT && !lag && !restart;
    wire bit_end = (phase == LAST && !lag) || restart;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rx_m <= 1'b1; rx_s <= 1'b1; rx_q <= 1'b1; sampled <= 1'b1; synced <= 1'b0;
            phase <= 6'd0; sync_kind <= 2'd0; can_tx <= 1'b1;
        end else begin
            rx_m <= can_rx; rx_s <= rx_m; rx_q <= rx_s;
            sync_kind <= hsync ? 2'd1 : lag ? 2'd2 : lead ? 2'd3 : 2'd0;
            if (use_edge && (hsync || resync)) synced <= 1'b1;
            if (sample_now) begin
                sampled <= rx_s;
                synced <= 1'b0;
            end
            if (restart) phase <= 6'd1;
            else if (lag) phase <= phase + 6'd1 - behind;
            else if (lead) phase <= phase + 6'd1 + JUMP > LAST ? 6'd0 : phase + 6'd1 + JUMP;
            else phase <= phase == LAST ? 6'd0 : phase + 6'd1;
            if (bit_end) can_tx <= tx_now;
        end
    end

    // ---------------------------------------------------------------- one sampled bit
    wire v = rx_s;
    wire tx_stuff = run_len == TX_STUFF_AT;
    wire rx_stuff = run_len == 3'd5;
    wire stuff_here = role_tx ? tx_stuff : rx_stuff;
    wire mismatch = role_tx && v != can_tx;
    wire in_arbitration = n >= 8'd1 && n <= 8'd12;
    wire lose = mismatch && can_tx && !stuff_here && in_arbitration && MUTATION != 4;
    wire keep = mismatch && can_tx && !stuff_here && in_arbitration && MUTATION == 4;
    wire [14:0] crc_next = {crc[13:0], 1'b0} ^ ((v ^ crc[14]) ? POLY : 15'd0);
    wire may_send = pend && !(passive && was_tx && MUTATION != 7);

    // Error and overload decisions for this sampled bit.
    reg [2:0] fault;
    reg       no_count;
    always @* begin
        fault = 3'd0;
        no_count = 1'b0;
        case (state)
            IDLE: if (!can_tx && v) fault = E_BIT;
            BODY: begin
                if (mismatch && !can_tx) fault = E_BIT;
                else if (mismatch && stuff_here) begin
                    fault = n <= 8'd12 ? E_STUFF : E_BIT;
                    no_count = n <= 8'd12;
                end else if (mismatch && !in_arbitration) fault = E_BIT;
                else if (rx_stuff && v == run_val && !keep) fault = E_STUFF;
            end
            TAIL: begin
                if (mismatch) fault = E_BIT;
                else if (v == run_val) fault = E_STUFF;
            end
            CRCDEL: if (!v) fault = E_FORM;
            ACK: begin
                if (role_tx && v) fault = E_ACK;
                else if (!role_tx && !can_tx && v) fault = E_BIT;
            end
            ACKDEL: begin
                if (!v) fault = E_FORM;
                else if (!role_tx && !crc_ok) fault = E_CRC;
            end
            EOFS: if (!v) fault = (!role_tx && cnt == 4'd6) ? E_OVERLOAD : E_FORM;
            IFS: if (!v && cnt < 4'd2) fault = E_OVERLOAD;
            DELIM: if (!v) fault = cnt == 4'd7 ? E_OVERLOAD : E_FORM;
            default: fault = 3'd0;
        endcase
    end

    wire is_error = fault != 3'd0 && fault != E_OVERLOAD;
    wire as_tx = role_tx || state == IDLE;                       // a start bit that is not seen
    wire hold_ack = fault == E_ACK && passive;
    wire [8:0] tec_step = MUTATION == 5 ? 9'd1 : 9'd8;
    wire [8:0] tec_up = tec_q + tec_step;
    wire [8:0] rec_up1 = {1'b0, rec_q} + 9'd1;
    wire [8:0] rec_up8 = {1'b0, rec_q} + 9'd8;
    wire flag_bit_error = state == FLAG && flag_kind != F_PASSIVE && v;
    wire held_ack_counts = state == FLAG && flag_kind == F_PASSIVE && !v && ack_hold;
    wire first_dominant = state == WAITR && !v && first_after && !role_tx && flag_kind != F_OVERLOAD;
    wire count_tx = (is_error && as_tx && !no_count && !hold_ack) || (flag_bit_error && role_tx) || held_ack_counts;
    wire bus_off_now = count_tx && tec_up >= 9'd256;
    wire start_frame = !v && (state == IDLE || state == SUSP || (state == IFS && cnt == 4'd2));
    wire start_as_tx = state == IDLE ? pend : state == IFS ? may_send : 1'b0;
    wire stuff_bit = state == BODY && fault == 3'd0 && stuff_here && !keep;
    wire data_bit = state == BODY && fault == 3'd0 && !stuff_bit;
    wire body_done = data_bit && n + 8'd1 == r_len;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pend <= 1'b0; b_id <= 11'd0; b_rtr <= 1'b0; b_dlc <= 4'd0; b_data <= 64'd0;
            state <= INTEG; role_tx <= 1'b0; was_tx <= 1'b0; n <= 8'd0; run_val <= 1'b0; run_len <= 3'd0;
            crc <= 15'd0; crc_ok <= 1'b0; r_id <= 11'd0; r_rtr <= 1'b0; r_dlc <= 4'd0; r_data <= 64'd0;
            cnt <= 4'd0; seq <= 8'd0; flag_kind <= F_ACTIVE; equal <= 3'd0; prev_bit <= 1'b0;
            first_after <= 1'b0; ack_hold <= 1'b0; tec_q <= 9'd0; rec_q <= 8'd0;
            tx_done <= 1'b0; rx_valid <= 1'b0; rx_id <= 11'd0; rx_rtr <= 1'b0; rx_dlc <= 4'd0; rx_data <= 64'd0;
            err_valid <= 1'b0; err_code <= 3'd0; arb_lost <= 1'b0;
        end else begin
            tx_done <= 1'b0; rx_valid <= 1'b0; err_valid <= 1'b0; arb_lost <= 1'b0;
            if (tx_valid && tx_ready) begin
                pend <= 1'b1; b_id <= tx_id; b_rtr <= tx_rtr; b_dlc <= tx_dlc; b_data <= tx_data;
            end
            if (sample_now) begin
                // ---- counters
                if (count_tx) tec_q <= tec_up;
                else if (is_error && !as_tx) rec_q <= rec_up1[8] ? 8'd255 : rec_up1[7:0];
                else if ((flag_bit_error && !role_tx) || first_dominant) rec_q <= rec_up8[8] ? 8'd255 : rec_up8[7:0];
                // ---- events
                if (fault != 3'd0 || flag_bit_error) begin
                    err_valid <= 1'b1;
                    err_code <= flag_bit_error ? E_BIT : fault;
                end
                // ---- state
                if (bus_off_now) begin
                    state <= OFF; cnt <= 4'd0; seq <= 8'd0;
                end else if (is_error) begin
                    state <= FLAG; cnt <= 4'd0; equal <= 3'd0;
                    flag_kind <= (passive && MUTATION != 6) ? F_PASSIVE : F_ACTIVE;
                    ack_hold <= hold_ack;
                    if (state == IDLE) begin
                        role_tx <= 1'b1; was_tx <= 1'b1;
                    end
                end else if (fault == E_OVERLOAD) begin
                    state <= FLAG; cnt <= 4'd0; flag_kind <= F_OVERLOAD; ack_hold <= 1'b0;
                end else if (start_frame) begin
                    state <= BODY; n <= 8'd1; run_val <= 1'b0; run_len <= 3'd1; crc <= 15'd0; crc_ok <= 1'b1;
                    role_tx <= start_as_tx; was_tx <= start_as_tx; r_data <= 64'd0;
                end else begin
                    case (state)
                        INTEG: begin
                            cnt <= v ? cnt + 4'd1 : 4'd0;
                            if (v && cnt == 4'd10) begin
                                state <= IDLE; cnt <= 4'd0;
                            end
                        end
                        OFF: begin
                            cnt <= v ? cnt + 4'd1 : 4'd0;
                            if (v && cnt == 4'd10) begin
                                cnt <= 4'd0; seq <= seq + 8'd1;
                                if (seq == 8'd127 || MUTATION == 10) begin
                                    state <= IDLE; tec_q <= 9'd0; rec_q <= 8'd0; role_tx <= 1'b0; was_tx <= 1'b0;
                                end
                            end
                        end
                        BODY: begin
                            if (lose) begin
                                role_tx <= 1'b0; was_tx <= 1'b0; arb_lost <= 1'b1;
                            end
                            if (stuff_bit) begin
                                run_val <= v; run_len <= 3'd1;
                            end else begin
                                n <= n + 8'd1;
                                run_val <= v;
                                run_len <= v == run_val ? run_len + 3'd1 : 3'd1;
                                if (n <= 8'd11) r_id[4'd11 - n[3:0]] <= v;
                                else if (n == 8'd12) r_rtr <= v;
                                else if (n >= 8'd15 && n <= 8'd18) r_dlc[2'd3 - (n[1:0] + 2'd1)] <= v;
                                else if (n >= 8'd19 && n < r_len - 8'd15) r_data[6'd63 - data_index] <= v;
                                if (n < r_len - 8'd15) crc <= crc_next;
                                else if (v != crc[4'd14 - crc_index]) crc_ok <= 1'b0;
                                if (body_done) state <= (v == run_val && run_len == 3'd4) ? TAIL : CRCDEL;
                            end
                        end
                        TAIL: state <= CRCDEL;
                        CRCDEL: state <= ACK;
                        ACK: begin
                            state <= ACKDEL;
                            if (!role_tx && crc_ok && !v && MUTATION != 9)
                                rec_q <= rec_q > 8'd127 ? 8'd127 : (rec_q == 8'd0 ? 8'd0 : rec_q - 8'd1);
                        end
                        ACKDEL: begin
                            state <= EOFS; cnt <= 4'd0;
                        end
                        EOFS: begin
                            cnt <= cnt + 4'd1;
                            if (!role_tx && cnt == 4'd5) begin
                                rx_valid <= 1'b1; rx_id <= r_id; rx_rtr <= r_rtr; rx_dlc <= r_dlc; rx_data <= r_data;
                            end
                            if (cnt == 4'd6) begin
                                state <= IFS; cnt <= 4'd0;
                                if (role_tx) begin
                                    tx_done <= 1'b1; pend <= 1'b0;
                                    tec_q <= tec_q == 9'd0 ? 9'd0 : tec_q - 9'd1;
                                end
                            end
                        end
                        IFS: begin
                            cnt <= cnt + 4'd1;
                            if (cnt == 4'd2) begin
                                state <= (passive && was_tx && MUTATION != 7) ? SUSP : IDLE; cnt <= 4'd0;
                            end
                        end
                        SUSP: begin
                            cnt <= cnt + 4'd1;
                            if (cnt == 4'd7) state <= IDLE;
                        end
                        FLAG: begin
                            if (flag_kind == F_PASSIVE) begin
                                if (held_ack_counts) ack_hold <= 1'b0;
                                prev_bit <= v; cnt <= 4'd1;
                                equal <= (cnt != 4'd0 && v == prev_bit) ? equal + 3'd1 : 3'd1;
                                if (cnt != 4'd0 && v == prev_bit && equal == 3'd5) begin
                                    state <= WAITR; first_after <= 1'b1;
                                end
                            end else if (v) cnt <= 4'd0;
                            else begin
                                cnt <= cnt + 4'd1;
                                if (cnt == 4'd5) begin
                                    state <= WAITR; first_after <= 1'b1;
                                end
                            end
                        end
                        WAITR: begin
                            first_after <= 1'b0;
                            if (v) begin
                                state <= DELIM; cnt <= 4'd1;
                            end
                        end
                        DELIM: begin
                            cnt <= cnt + 4'd1;
                            if (cnt == 4'd7) begin
                                state <= IFS; cnt <= 4'd0;
                            end
                        end
                        default: state <= state;
                    endcase
                end
            end
        end
    end
endmodule
