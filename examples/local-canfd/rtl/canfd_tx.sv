// Serial transmitter for 11-bit classical and ISO FD data frames. The two
// phases use integral clock periods; bit_valid marks the first tick of a bit.
module canfd_tx #(parameter RATIO=3, MUTATION=0)(
    input wire clk, rst_n, start, fd, brs,
    input wire [10:0] identifier,
    input wire [3:0] dlc,
    input wire [511:0] payload,  // first octet is payload[511:504]
    output reg busy, bit_valid, tx, stuffed, fast
);
    localparam BODY=0, SBC=1, CRC=2, TAIL=3;
    reg [1:0] state;
    reg fd_q, brs_q;
    reg [21:0] header;
    reg [511:0] data_q;
    reg [9:0] index_q, body_length;
    reg [4:0] width_q;
    reg [20:0] crc_q, polynomial;
    reg [2:0] run_length, stuff_count;
    reg [2:0] group_size;
    reg last, extra_tail_stuff;
    reg [1:0] sbc_index;
    reg [3:0] tail_index;
    integer ticks;
    reg finish_pending;

    function [6:0] length_bytes(input [3:0] code, input flexible);
        case (code)
            9: length_bytes = flexible ? 12 : 8;
            10: length_bytes = flexible ? 16 : 8;
            11: length_bytes = flexible ? 20 : 8;
            12: length_bytes = flexible ? 24 : 8;
            13: length_bytes = flexible ? 32 : 8;
            14: length_bytes = flexible ? 48 : 8;
            15: length_bytes = flexible ? 64 : 8;
            default: length_bytes = {3'b000,code};
        endcase
    endfunction

    wire long_crc = fd && dlc >= 11 && MUTATION != 2;
    wire [9:0] header_length = fd_q ? 22 : 19;
    wire [9:0] last_crc_bit = {5'b0,width_q} - 10'd1;
    wire [2:0] gray = stuff_count ^ (stuff_count >> 1);
    wire [3:0] sbc_bits = {gray, ^gray};
    wire dynamic_region = state == BODY || (!fd_q && state == CRC);
    wire dynamic_stuff = dynamic_region && run_length == (MUTATION == 1 ? 6 : 5);
    wire fixed_stuff = fd_q && (state == SBC || state == CRC) && group_size == 4;
    wire tail_stuff = state == TAIL && extra_tail_stuff;
    wire insert_bit = dynamic_stuff || fixed_stuff || tail_stuff;
    wire is_fast = brs_q && (state == BODY ? index_q >= 17 : state != TAIL);
    reg value;
    always @* begin
        if (insert_bit) value = !last;
        else case (state)
            BODY: value = index_q < header_length ? header[21-index_q] :
                          data_q[511-(index_q-header_length)];
            SBC: value = sbc_bits[3-sbc_index];
            CRC: value = crc_q[last_crc_bit[4:0]-index_q[4:0]];
            default: value = 1;
        endcase
    end
    wire crc_feedback = crc_q[width_q-1] ^ value;
    wire [20:0] crc_next = (crc_q << 1) ^ (crc_feedback ? polynomial : 21'd0);
    wire [2:0] next_run = (last == value) ? run_length + 1'b1 : 3'd1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy <= 0; bit_valid <= 0; tx <= 1; stuffed <= 0; fast <= 0;
            ticks <= 0; finish_pending <= 0;
        end else begin
            bit_valid <= 0;
            if (!busy && start) begin
                busy <= 1; state <= BODY; index_q <= 0; ticks <= 0;
                fd_q <= fd; brs_q <= fd && brs && MUTATION != 3;
                data_q <= payload; last <= 1; run_length <= 0; stuff_count <= 0;
                group_size <= 4; extra_tail_stuff <= 0; sbc_index <= 0;
                tail_index <= 0; finish_pending <= 0;
                if (fd)
                    header <= {1'b0, identifier, 2'b00, MUTATION != 4, 1'b0, brs, 1'b0, dlc};
                else
                    header <= {1'b0, identifier, 3'b000, dlc, 3'b000};
                body_length <= (fd ? 22 : 19) + 8 * length_bytes(dlc, fd);
                width_q <= fd ? (long_crc ? 21 : 17) : 15;
                polynomial <= fd ? (long_crc ? 21'h102899 : 21'h01685b) : 21'h004599;
                crc_q <= fd ? (long_crc ? 21'h100000 : 21'h010000) : 0;
            end else if (busy && ticks != 0) begin
                ticks <= ticks - 1;
            end else if (busy && finish_pending) begin
                busy <= 0; fast <= 0; stuffed <= 0; finish_pending <= 0;
            end else if (busy) begin
                bit_valid <= 1; tx <= value; fast <= is_fast; stuffed <= insert_bit;
                ticks <= is_fast ? 0 : RATIO-1;
                last <= value; run_length <= next_run;
                if ((state == BODY && (!dynamic_stuff || fd_q)) || (state == SBC && !fixed_stuff))
                    crc_q <= crc_next;
                if (dynamic_stuff) stuff_count <= stuff_count + 1'b1;
                else if (fixed_stuff) group_size <= 0;
                else if (tail_stuff) extra_tail_stuff <= 0;
                else case (state)
                    BODY: begin
                        if (index_q == body_length-1) begin
                            state <= fd_q ? SBC : CRC;
                            index_q <= 0;
                        end else index_q <= index_q + 1'b1;
                    end
                    SBC: begin
                        group_size <= group_size + 1'b1;
                        sbc_index <= sbc_index + 1'b1;
                        if (sbc_index == 3) state <= CRC;
                    end
                    CRC: begin
                        group_size <= group_size + 1'b1;
                        index_q <= index_q + 1'b1;
                        if (index_q == last_crc_bit) begin
                            state <= TAIL;
                            extra_tail_stuff <= !fd_q && next_run == 5;
                        end
                    end
                    TAIL: begin
                        tail_index <= tail_index + 1'b1;
                        if (tail_index == 12) finish_pending <= 1;
                    end
                endcase
            end
        end
    end
endmodule
