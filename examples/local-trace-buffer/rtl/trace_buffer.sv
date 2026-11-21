// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// On-chip trace buffer: a ring of DEPTH samples with a trigger, a post-trigger length and a
// readout port, oldest sample first.
//
// arm (a one-clock pulse) latches the configuration and starts a capture on the next clock;
// arm during a capture restarts it. While capturing, every clock writes the sample. The first
// sample on which the trigger holds is the trigger sample; post more samples are written after
// it, then the buffer freezes (done). The window is the last min(written, DEPTH) samples, so
// the samples before the trigger are those that fit. In done, each rd_req returns the next
// sample of the window on the following clock, with rd_trig on the trigger sample and rd_last on
// the newest; requests after the last one, and requests while not done, are ignored.
module trace_buffer #(parameter DEPTH = 16, W = 9, MUTATION = 0) (
    input wire clk, rst_n,
    input wire arm,
    input wire [$clog2(DEPTH)-1:0] post,
    input wire trig_sel,                         // 0: (sample & mask) == (value & mask), 1: ext_trig
    input wire [W-1:0] trig_value, trig_mask,
    input wire ext_trig,
    input wire [W-1:0] sample,
    input wire rd_req,
    output wire busy, done,
    output reg [$clog2(DEPTH):0] kept,
    output reg rd_valid, rd_trig, rd_last,
    output reg [W-1:0] rd_data
);
    localparam AW = $clog2(DEPTH);
    localparam [1:0] IDLE = 2'd0, ARMED = 2'd1, POST = 2'd2, DONE = 2'd3;
    localparam [AW:0] FULL = DEPTH[AW:0];
    localparam [AW-1:0] EXTRA = MUTATION == 2 ? 1 : 0;
    reg [1:0] state;
    reg [W-1:0] mem [0:DEPTH-1];
    reg [AW-1:0] wr_ptr, trig_ptr, rd_ptr, remaining, post_q;
    reg [AW:0] rd_left;
    reg sel_q;
    reg [W-1:0] value_q, mask_q;
    wire match = MUTATION == 6 ? sample == value_q : (sample & mask_q) == (value_q & mask_q);
    wire hit = (state == ARMED || (MUTATION == 5 && state == POST)) && (sel_q ? ext_trig : match);
    wire [AW:0] kept_next = (kept == FULL && MUTATION != 4) ? kept : kept + 1'b1;
    wire [AW-1:0] wr_next = wr_ptr + 1'b1;
    // The oldest sample of the window once the current sample is written.
    wire [AW-1:0] oldest = MUTATION == 3 ? wr_next : wr_next - kept_next[AW-1:0];
    assign busy = state == ARMED || state == POST;
    assign done = state == DONE;

    always @(posedge clk) begin
        rd_valid <= 1'b0;
        rd_trig <= 1'b0;
        rd_last <= 1'b0;
        if (!rst_n) begin
            state <= IDLE; wr_ptr <= 0; trig_ptr <= 0; rd_ptr <= 0; remaining <= 0; post_q <= 0;
            rd_left <= 0; kept <= 0; sel_q <= 0; value_q <= 0; mask_q <= 0; rd_data <= 0;
        end else if (arm) begin
            state <= ARMED; wr_ptr <= 0; kept <= 0; rd_left <= 0;
            post_q <= post; sel_q <= trig_sel; value_q <= trig_value; mask_q <= trig_mask;
        end else if (busy) begin
            mem[wr_ptr] <= sample;
            wr_ptr <= wr_next;
            kept <= kept_next;
            if (hit) begin
                trig_ptr <= wr_ptr;
                if (post_q == 0) begin
                    state <= DONE; rd_ptr <= oldest; rd_left <= kept_next;
                end else begin
                    state <= POST; remaining <= post_q + EXTRA;
                end
            end else if (state == POST) begin
                if (remaining == 1) begin
                    state <= DONE; rd_ptr <= oldest; rd_left <= kept_next;
                end else remaining <= remaining - 1'b1;
            end
        end else if (done && rd_req && rd_left != 0) begin
            rd_valid <= 1'b1;
            rd_data <= mem[rd_ptr];
            rd_trig <= rd_ptr == (MUTATION == 7 ? trig_ptr + 1'b1 : trig_ptr);
            rd_last <= rd_left == 1;
            rd_ptr <= rd_ptr + 1'b1;
            rd_left <= rd_left - 1'b1;
        end
    end
endmodule
