// Receive packet layer of a teaching-only sensor link. The format is this example's own:
// it is not an implementation of any published interface and claims no compatibility.
//
// Lanes: each lane strobes one byte at a time (lane_valid) while lane_active is high. The
// first byte of a burst on every lane is SYNC. Stream byte k travels on lane k % LANES.
// A four-deep FIFO per lane absorbs the skew between lanes; bytes are merged round robin.
// Packet: type, count low, count high, ECC (SEC-DED over the 24 bits). Types with bit 5 set
// carry `count` payload bytes and a 16-bit CRC, low byte first.
module sensor_packet_rx #(parameter LANES = 2, MAX_LINE = 8, MUTATION = 0)(
    input wire clk, rst_n,
    input wire [LANES-1:0] lane_active, lane_valid,
    input wire [8*LANES-1:0] lane_data,
    output reg pix_valid,
    output reg [7:0] pix_data,
    output reg pix_first, pix_last,
    output reg row_done, row_ok,
    output reg frame_start, frame_end, frame_clean,
    output reg [15:0] evt_num,
    output reg hdr_fix, pkt_ignored,
    output reg [5:0] err              // {lane, truncated, count, sequence, crc, header}
);
    localparam DEPTH = 4;
    localparam [7:0] SYNC = 8'hb8;
    localparam LW = LANES > 1 ? $clog2(LANES) : 1;
    localparam [7:0] T_FS = 8'h00, T_FE = 8'h01, T_LS = 8'h02, T_LE = 8'h03, T_ROW = 8'h2a;
    localparam [2:0] P_H0 = 3'd0, P_H1 = 3'd1, P_H2 = 3'd2, P_H3 = 3'd3, P_PAY = 3'd4, P_C0 = 3'd5, P_C1 = 3'd6;
    // Parity masks and codeword positions of the 24 header bits (positions 1..29 without powers of two).
    localparam [23:0] MASK0 = 24'haaad5b, MASK1 = 24'h33366d, MASK2 = 24'hc3c78e,
                      MASK3 = 24'hfc07f0, MASK4 = 24'hfff800;
    localparam [119:0] POS = {5'd29, 5'd28, 5'd27, 5'd26, 5'd25, 5'd24, 5'd23, 5'd22, 5'd21, 5'd20, 5'd19, 5'd18,
                              5'd17, 5'd15, 5'd14, 5'd13, 5'd12, 5'd11, 5'd10, 5'd9, 5'd7, 5'd6, 5'd5, 5'd3};

    // Lane FIFOs.
    reg [8*DEPTH-1:0] store [0:LANES-1];
    reg [2:0] count [0:LANES-1];
    reg [1:0] rd [0:LANES-1], wr [0:LANES-1];
    reg [LANES-1:0] synced, ended;
    reg drop;
    reg [LW-1:0] rr;
    // Parser.
    reg [2:0] ps;
    reg [7:0] h0, h1, h2, crc_lo;
    reg [15:0] remaining, crc;
    reg first, emit;
    reg in_frame, in_line, row_seen, dirty, width_set;
    reg [15:0] width, frame_no, line_cnt;

    function automatic [15:0] crc_step(input [15:0] c, input [7:0] b);
        integer k;
        reg [15:0] x;
        begin
            x = c ^ {8'd0, b};
            for (k = 0; k < 8; k = k + 1) x = x[0] ? (x >> 1) ^ 16'h8408 : x >> 1;
            crc_step = x;
        end
    endfunction

    // Lane and merge control.
    wire running = &synced;
    wire can_pop = !drop && running && count[rr] != 3'd0;
    wire [7:0] popped = store[rr][8*rd[rr] +: 8];
    wire stream_end = !drop && running && count[rr] == 3'd0 && !lane_active[rr];
    // A burst in which some lane never sent its first byte before every lane went quiet.
    wire lane_missing = !drop && !running && |synced && lane_active == {LANES{1'b0}};
    // A lane has one active interval per burst: coming back after it ended is the next burst, too early.
    wire lane_restart = !drop && |(ended & lane_active);

    // Header decode: {usable, corrected, type, count}.
    reg [23:0] hd, fixed_hd;
    reg [4:0] syn;
    reg overall, usable, corrected;
    reg [7:0] ecc;
    integer d;
    always_comb begin
        ecc = popped;
        hd = {h2, h1, h0};
        syn = {^(hd & MASK4) ^ ecc[4], ^(hd & MASK3) ^ ecc[3], ^(hd & MASK2) ^ ecc[2],
               ^(hd & MASK1) ^ ecc[1], ^(hd & MASK0) ^ ecc[0]};
        overall = ^hd ^ ^ecc[5:0];
        fixed_hd = hd;
        for (d = 0; d < 24; d = d + 1)
            if (overall && syn == (MUTATION == 1 ? POS[5*d +: 5] ^ 5'd1 : POS[5*d +: 5])) fixed_hd[d] = !hd[d];
        // One error has odd overall parity and names a real position; two have even parity.
        usable = ecc[7:6] == 2'b00 &&
                 (overall ? syn <= 5'd29 : syn == 5'd0 || MUTATION == 2);
        corrected = usable && (overall || syn != 5'd0);
    end
    wire [7:0] dtype = fixed_hd[7:0];
    wire [15:0] dwc = fixed_hd[23:8];
    localparam [15:0] LINE_LIMIT = MAX_LINE[15:0];  // sized, so a parameter override does not widen the comparison

    reg [LANES-1:0] push, bad_sync, overflow;
    reg leftover;
    integer i;
    always_comb begin
        leftover = |lane_active;
        for (i = 0; i < LANES; i = i + 1) begin
            push[i] = !drop && lane_active[i] && lane_valid[i] && synced[i];
            bad_sync[i] = !drop && lane_active[i] && lane_valid[i] && !synced[i] && lane_data[8*i +: 8] != SYNC;
            overflow[i] = push[i] && count[i] == DEPTH[2:0] && !(can_pop && rr == i[LW-1:0]) && MUTATION != 8;
            if (count[i] != 3'd0) leftover = 1'b1;
        end
    end
    wire lane_error = |bad_sync || |overflow || lane_missing || lane_restart;
    wire take = can_pop && !lane_error;

    // What the byte taken in this clock does.
    reg [5:0] e;
    reg n_in_frame, n_in_line, n_row_seen, n_width_set, n_emit, clear_dirty;
    reg [15:0] n_width, n_frame_no, n_line_cnt;
    reg [2:0] n_ps;
    reg n_drop, n_fs, n_fe, n_clean, n_fix, n_ign, n_pix, n_first, n_last, n_done, n_ok, to_idle;
    reg [15:0] n_num;
    reg seq_bad, wc_bad;
    always_comb begin
        e = 6'd0;
        n_in_frame = in_frame; n_in_line = in_line; n_row_seen = row_seen; n_width_set = width_set;
        n_emit = emit; n_width = width; n_frame_no = frame_no; n_line_cnt = line_cnt;
        n_ps = ps; n_drop = drop; clear_dirty = 1'b0; to_idle = 1'b0;
        {n_fs, n_fe, n_clean, n_fix, n_ign, n_pix, n_first, n_last, n_done, n_ok} = 10'd0;
        n_num = 16'd0;
        seq_bad = 1'b0; wc_bad = 1'b0;
        if (drop) begin
            n_ps = P_H0;
            if (lane_active == {LANES{1'b0}}) n_drop = 1'b0;
        end else if (lane_error) begin
            e[5] = 1'b1; n_drop = 1'b1; n_ps = P_H0;
        end else if (take) begin
            case (ps)
                P_H0, P_H1, P_H2: n_ps = ps + 3'd1;
                P_H3: begin
                    n_ps = P_H0;
                    if (!usable) begin
                        e[0] = 1'b1; n_drop = 1'b1;
                    end else begin
                        n_fix = corrected;
                        if (!dtype[5]) begin
                            case (dtype)
                                T_FS: begin
                                    n_fs = 1'b1; n_num = dwc;
                                    if (in_frame) e[2] = 1'b1; else clear_dirty = 1'b1;
                                    n_in_frame = 1'b1; n_in_line = 1'b0; n_row_seen = 1'b0;
                                    n_line_cnt = 16'd0; n_width_set = 1'b0; n_frame_no = dwc;
                                end
                                T_FE: begin
                                    if (!in_frame) e[2] = 1'b1;
                                    else begin
                                        seq_bad = in_line || dwc != frame_no;
                                        e[2] = seq_bad;
                                        n_fe = 1'b1; n_num = frame_no;
                                        n_clean = !dirty && !seq_bad;
                                        n_in_frame = 1'b0; n_in_line = 1'b0;
                                    end
                                end
                                T_LS: begin
                                    if (!in_frame || in_line) e[2] = 1'b1;
                                    else begin
                                        e[2] = dwc != line_cnt;
                                        n_in_line = 1'b1; n_row_seen = 1'b0;
                                    end
                                end
                                T_LE: begin
                                    if (!in_line) e[2] = 1'b1;
                                    else begin
                                        e[2] = !row_seen || dwc != line_cnt;
                                        n_in_line = 1'b0; n_line_cnt = line_cnt + 16'd1;
                                    end
                                end
                                default: n_ign = 1'b1;
                            endcase
                        end else begin
                            n_ps = dwc == 16'd0 ? P_C0 : P_PAY;
                            n_emit = 1'b0;
                            if (dtype == T_ROW) begin
                                seq_bad = (!in_line || row_seen) && MUTATION != 5;
                                wc_bad = dwc == 16'd0 || dwc > (MUTATION == 6 ? LINE_LIMIT + 16'd1 : LINE_LIMIT) ||
                                         (width_set && dwc != width && MUTATION != 10);
                                if (seq_bad) e[2] = 1'b1;
                                else begin
                                    n_row_seen = 1'b1;
                                    if (wc_bad) e[3] = 1'b1;
                                    else begin
                                        n_emit = 1'b1;
                                        if (!width_set) begin n_width = dwc; n_width_set = 1'b1; end
                                    end
                                end
                            end else n_ign = 1'b1;
                        end
                    end
                end
                P_PAY: begin
                    n_pix = emit; n_first = emit && first; n_last = emit && remaining == 16'd1;
                    if (remaining == 16'd1) n_ps = P_C0;
                end
                P_C0: n_ps = P_C1;
                default: begin          // P_C1
                    n_ps = P_H0;
                    n_done = emit;
                    n_ok = emit && {popped, crc_lo} == crc;
                    e[1] = emit && {popped, crc_lo} != crc;
                end
            endcase
        end else if (stream_end) begin
            // The lane whose turn it is has ended: the stream is over.
            n_ps = P_H0;
            e[4] = ps != P_H0 && MUTATION != 7;
            e[5] = leftover;
            if (leftover) n_drop = 1'b1; else to_idle = 1'b1;
        end
    end

    integer j;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (j = 0; j < LANES; j = j + 1) begin
                count[j] <= 3'd0; rd[j] <= 2'd0; wr[j] <= 2'd0; store[j] <= {8*DEPTH{1'b0}};
            end
            synced <= {LANES{1'b0}}; ended <= {LANES{1'b0}}; drop <= 1'b0; rr <= {LW{1'b0}};
            ps <= P_H0; h0 <= 8'd0; h1 <= 8'd0; h2 <= 8'd0; crc_lo <= 8'd0;
            remaining <= 16'd0; crc <= 16'd0; first <= 1'b0; emit <= 1'b0;
            in_frame <= 1'b0; in_line <= 1'b0; row_seen <= 1'b0; dirty <= 1'b0; width_set <= 1'b0;
            width <= 16'd0; frame_no <= 16'd0; line_cnt <= 16'd0;
            pix_valid <= 1'b0; pix_data <= 8'd0; pix_first <= 1'b0; pix_last <= 1'b0;
            row_done <= 1'b0; row_ok <= 1'b0; frame_start <= 1'b0; frame_end <= 1'b0; frame_clean <= 1'b0;
            evt_num <= 16'd0; hdr_fix <= 1'b0; pkt_ignored <= 1'b0; err <= 6'd0;
        end else begin
            // Lanes.
            if (drop || n_drop || to_idle) begin
                for (j = 0; j < LANES; j = j + 1) begin count[j] <= 3'd0; rd[j] <= 2'd0; wr[j] <= 2'd0; end
                synced <= {LANES{1'b0}};
                ended <= {LANES{1'b0}};
                if (!(MUTATION == 4 && to_idle)) rr <= {LW{1'b0}};
            end else begin
                for (j = 0; j < LANES; j = j + 1) begin
                    if (lane_active[j] && lane_valid[j] && !synced[j]) synced[j] <= 1'b1;
                    if (synced[j] && !lane_active[j]) ended[j] <= 1'b1;
                    if (push[j]) begin
                        store[j][8*wr[j] +: 8] <= lane_data[8*j +: 8];
                        if (!(count[j] == DEPTH[2:0] && !(take && rr == j[LW-1:0]))) wr[j] <= wr[j] + 2'd1;
                    end
                    if (take && rr == j[LW-1:0]) rd[j] <= rd[j] + 2'd1;
                    if (push[j] && !(take && rr == j[LW-1:0])) begin
                        if (count[j] != DEPTH[2:0]) count[j] <= count[j] + 3'd1;
                    end else if (!push[j] && take && rr == j[LW-1:0]) count[j] <= count[j] - 3'd1;
                end
                if (take) rr <= {1'b0, rr} == LANES[LW:0] - 1'b1 ? {LW{1'b0}} : rr + 1'b1;
            end
            drop <= n_drop;
            // Parser.
            ps <= n_ps;
            if (take) begin
                case (ps)
                    P_H0: h0 <= popped;
                    P_H1: h1 <= popped;
                    P_H2: h2 <= popped;
                    P_H3: begin remaining <= dwc; crc <= MUTATION == 3 ? 16'h0000 : 16'hffff; first <= 1'b1; end
                    P_PAY: begin crc <= crc_step(crc, popped); remaining <= remaining - 16'd1; first <= 1'b0; end
                    P_C0: crc_lo <= popped;
                    default: ;
                endcase
            end
            emit <= n_emit;
            in_frame <= n_in_frame; in_line <= n_in_line; row_seen <= n_row_seen; width_set <= n_width_set;
            width <= n_width; frame_no <= n_frame_no; line_cnt <= n_line_cnt;
            // A frame is clean only when nothing was reported between its start and its end.
            if (clear_dirty) dirty <= 1'b0;
            else if (e != 6'd0 && n_in_frame && !(MUTATION == 9 && e == 6'b000010)) dirty <= 1'b1;
            pix_valid <= n_pix; pix_data <= n_pix ? popped : 8'd0; pix_first <= n_first; pix_last <= n_last;
            row_done <= n_done; row_ok <= n_ok;
            frame_start <= n_fs; frame_end <= n_fe; frame_clean <= n_clean; evt_num <= n_num;
            hdr_fix <= n_fix; pkt_ignored <= n_ign; err <= e;
        end
    end
endmodule
