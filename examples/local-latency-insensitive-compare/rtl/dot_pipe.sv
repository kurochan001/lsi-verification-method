// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Pipelined 4-lane dot product: one transaction per clock. Stage A holds the four
// products, an optional stage S (SPLIT=1) holds two pair sums, stage B holds the
// final sum and a 2-entry FIFO decouples the output. Each stage moves when the
// next one has room, so a stalled output fills the pipeline from the end.
module dot_pipe #(
    parameter integer SPLIT = 0,
    parameter integer MUTATION = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        in_valid,
    output wire        in_ready,
    input  wire [63:0] in_data,
    output wire        out_valid,
    input  wire        out_ready,
    output wire [17:0] out_data
);
    wire signed [7:0] a0 = in_data[7:0];
    wire signed [7:0] a1 = in_data[15:8];
    wire signed [7:0] a2 = in_data[23:16];
    wire signed [7:0] a3 = in_data[31:24];
    wire signed [7:0] b0 = in_data[39:32];
    wire signed [7:0] b1 = in_data[47:40];
    wire signed [7:0] b2 = in_data[55:48];
    wire signed [7:0] b3 = in_data[63:56];
    wire signed [15:0] q0 = a0 * b0;
    wire signed [15:0] q1 = a1 * b1;
    wire signed [15:0] q2 = a2 * b2;
    wire signed [15:0] q3s = a3 * b3;
    wire [15:0] q3u = {8'd0, in_data[31:24]} * {8'd0, in_data[63:56]};
    // Mutation 6: lane 3 multiplies without sign.
    wire [15:0] q3 = MUTATION == 6 ? q3u : q3s;

    reg vA, vB;
    reg signed [15:0] p0, p1, p2, p3;
    reg signed [17:0] dB;
    reg [17:0] mem0, mem1;
    reg rptr, wptr, stalled, waiting, withdrawn;
    reg [1:0] count;

    wire signed [16:0] pa = {p0[15], p0} + {p1[15], p1};
    wire signed [16:0] pb = {p2[15], p2} + {p3[15], p3};

    // Mutation 4: a result that has waited one cycle is withdrawn for one cycle, once per result.
    wire withdraw = MUTATION == 4 && waiting && !withdrawn;
    wire valid_out = count != 2'd0 && !withdraw;
    assign out_valid = rst_n && valid_out;
    wire pop = out_valid && out_ready;
    wire push_ok = vB && (count != 2'd2 || pop);

    wire feed_v;
    wire signed [17:0] feed_sum;
    wire a_next_ready;
    // Mutation 1: on the cycle a stall ends, the newer sum bypasses stage B.
    wire swap_now = MUTATION == 1 && stalled && vB && feed_v && push_ok;
    // Mutation 3: stage B takes a new sum even when its own cannot leave.
    wire rB = !vB || push_ok || (MUTATION == 3 && feed_v);
    wire rA = !vA || a_next_ready;
    assign in_ready = rst_n && rA;
    wire accept = in_valid && in_ready;
    // Mutation 2: a push and a pop in the same cycle at one entry ignore the pop.
    wire pop_eff = pop && !(MUTATION == 2 && push_ok && count == 2'd1);

    wire [17:0] head = rptr ? mem1 : mem0;
    wire [17:0] other = rptr ? mem0 : mem1;
    // Mutation 7: while waiting with two entries, the output shows the newer one.
    assign out_data = (MUTATION == 7 && count == 2'd2 && !out_ready) ? other : head;
    wire [17:0] push_data = swap_now ? feed_sum : dB;

    generate
        if (SPLIT != 0) begin : g_split
            reg vS;
            reg signed [16:0] s0, s1;
            assign a_next_ready = !vS || rB;
            assign feed_v = vS;
            assign feed_sum = {s0[16], s0} + {s1[16], s1};
            always @(posedge clk) begin
                if (!rst_n) vS <= 1'b0;
                else if (a_next_ready) begin
                    vS <= vA;
                    s0 <= pa;
                    s1 <= pb;
                end
            end
        end else begin : g_flat
            assign a_next_ready = rB;
            assign feed_v = vA;
            assign feed_sum = {pa[16], pa} + {pb[16], pb};
        end
    endgenerate

    always @(posedge clk) begin
        if (!rst_n) begin
            vA <= 1'b0;
            // Mutation 5: reset leaves stage B valid, so a stale sum appears afterwards.
            if (MUTATION != 5) vB <= 1'b0;
            count <= 2'd0;
            rptr <= 1'b0;
            wptr <= 1'b0;
            stalled <= 1'b0;
            waiting <= 1'b0;
            withdrawn <= 1'b0;
        end else begin
            waiting <= out_valid && !out_ready;
            if (pop) withdrawn <= 1'b0;
            else if (withdraw) withdrawn <= 1'b1;
            stalled <= vB && !push_ok;
            if (rA) begin
                vA <= accept;
                p0 <= q0;
                p1 <= q1;
                p2 <= q2;
                p3 <= q3;
            end
            if (rB && !swap_now) begin
                vB <= feed_v;
                dB <= feed_sum;
            end
            if (push_ok) begin
                if (wptr) mem1 <= push_data;
                else mem0 <= push_data;
                wptr <= !wptr;
            end
            if (pop_eff) rptr <= !rptr;
            count <= count + {1'b0, push_ok} - {1'b0, pop_eff};
        end
    end
endmodule
