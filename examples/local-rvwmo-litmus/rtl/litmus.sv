// Store-buffer litmus harness (RVWMO SB pattern), fence as an instruction input.
// Hart 0: store X=1, [FENCE], load r0=Y.   Hart 1: store Y=1, [FENCE], load r1=X.
// Each hart has a one-entry store buffer that drains DRAIN cycles after issue.
// A FENCE pulse arms a wait that retires when the buffer empties, so a load
// after the fence sees its own store published: the litmus outcome r0=r1=0
// becomes impossible. Stimulus without fences allows it.
// Race rule: the drain retiring on the same edge as a FENCE pulse retires the
// fence immediately, and a load samples the pre-clock-edge value.
module litmus #(parameter DRAIN=2, MUTATION=0)(
    input wire clk, rst_n,
    input wire issue0, issue1, read0, read1, fence0, fence1,
    output reg x, y,
    output reg vis0, vis1,
    output wire busy0, busy1,
    output reg fwait0, fwait1,
    output reg done0, done1,
    output reg r0, r1
);
    reg pend0, pend1;
    reg [3:0] t0, t1;
    reg fsaw0, fsaw1;
    assign busy0 = pend0;
    assign busy1 = pend1;
    wire drain0 = pend0 && t0 == 0;
    wire drain1 = pend1 && t1 == 0;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            x <= 0; y <= 0; vis0 <= 0; vis1 <= 0;
            pend0 <= 0; pend1 <= 0; t0 <= 0; t1 <= 0;
            fsaw0 <= 0; fsaw1 <= 0; fwait0 <= 0; fwait1 <= 0;
            done0 <= 0; done1 <= 0; r0 <= 0; r1 <= 0;
        end else begin
            // hart 0: countdown, drain publishes X and retires a waiting fence.
            if (drain0) begin
                pend0 <= 0; vis0 <= 1; fwait0 <= 0;
                if (MUTATION == 2) y <= 1; else x <= 1;
            end else if (issue0 && !pend0 && !vis0) begin
                pend0 <= 1;
                t0 <= MUTATION == 3 ? DRAIN[3:0] - 2 : DRAIN[3:0] - 1;
            end else if (pend0) begin
                t0 <= t0 - 1;
            end
            // FENCE waits only while a store is still buffered; one fence per run.
            if (fence0 && !fsaw0 && pend0 && !drain0) fwait0 <= 1;
            if (fence0 && !fsaw0) fsaw0 <= 1;
            if (read0 && !done0 && (MUTATION == 1 || !fwait0)) begin
                done0 <= 1;
                r0 <= MUTATION == 4 ? x : y;
            end
            // hart 1: symmetric, drain publishes Y.
            if (drain1) begin
                pend1 <= 0; vis1 <= 1; fwait1 <= 0;
                y <= 1;  // MUTATION 2 is hart 0 only: its drain hits the wrong line
            end else if (issue1 && !pend1 && !vis1) begin
                pend1 <= 1;
                t1 <= MUTATION == 3 ? DRAIN[3:0] - 2 : DRAIN[3:0] - 1;
            end else if (pend1) begin
                t1 <= t1 - 1;
            end
            if (fence1 && !fsaw1 && pend1 && !drain1) fwait1 <= 1;
            if (fence1 && !fsaw1) fsaw1 <= 1;
            if (read1 && !done1 && (MUTATION == 1 || !fwait1)) begin
                done1 <= 1;
                r1 <= MUTATION == 4 ? y : x;
            end
        end
    end
endmodule
