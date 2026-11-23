module plic #(parameter NS=4, MUTATION=0)(
    input wire clk, rst_n,
    input wire psel, pwrite,
    input wire [1:0] ridx,
    input wire [31:0] wdata,
    input wire [7:0] set,
    output reg [31:0] rdata,
    output wire [7:0] pending, inservice,
    output reg [7:0] cand_ge,
    output reg [3:0] pick,
    output wire irq
);
    // R0 PRI: source s priority is wdata[3*s+2:3*s]; 0 never becomes a candidate.
    // R1 THRESH: a candidate needs priority > threshold.  R2 CLAIM: read the ID.
    // R3 COMPLETE: write the ID to finish service.  Reads of R3 return 0.
    reg [2:0] pri [0:7];
    reg [2:0] thresh;
    reg [7:0] pending_r, inservice_r;
    reg [7:0] next_pending, next_inservice;
    reg [2:0] best_pri;
    reg [3:0] best;
    wire claim_read = psel && !pwrite && ridx == 2'd2;
    wire [7:0] ns_mask = 8'hff >> (8 - NS);
    wire [7:0] set_mask = set & ns_mask;
    wire [7:0] claim_bit = (claim_read && best != 0) ? (8'h01 << (best - 4'd1)) : 8'h00;
    wire [3:0] cid = wdata[3:0];
    wire complete_ok = psel && pwrite && ridx == 2'd3 &&
        wdata != 0 && wdata <= NS && inservice_r[cid[2:0] - 3'd1];
    wire [7:0] complete_bit = complete_ok ? (8'h01 << (cid - 4'd1)) : 8'h00;

    always @* begin
        best = 0; best_pri = 0;
        for (integer s = 0; s < 8; s = s + 1) begin
            if (s < NS && pending_r[s] && !inservice_r[s] && pri[s] > thresh &&
                (MUTATION == 3 ? pri[s] >= best_pri : pri[s] > best_pri)) begin
                best = s[3:0] + 4'd1; best_pri = pri[s];
            end
        end
        pick = best;
    end

    always @* begin
        cand_ge = 0;
        for (integer s = 0; s < 8; s = s + 1)
            if (s < NS && pending_r[s] && !inservice_r[s] &&
                pri[s] != 0 && pri[s] >= thresh) cand_ge[s] = 1'b1;
    end

    assign pending = pending_r;
    assign inservice = inservice_r;
    assign irq = MUTATION == 1 ? (cand_ge != 0) : (best != 0);

    always @* begin
        rdata = 0;
        if (psel) case (ridx)
            2'd0: begin
                for (integer s = 0; s < 8; s = s + 1) rdata[s*3 +: 3] = pri[s];
            end
            2'd1: rdata = {29'b0, thresh};
            2'd2: rdata = pwrite ? 32'd0 : {28'd0, best};
            default: rdata = 0;
        endcase
    end

    always @* begin
        next_pending = (pending_r & ~claim_bit) |
            (MUTATION == 4 ? set_mask & ~claim_bit : set_mask);
        next_inservice = inservice_r | claim_bit;
        if (complete_ok) begin
            if (MUTATION == 2) next_pending = next_pending & ~complete_bit;
            else next_inservice = next_inservice & ~complete_bit;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pending_r <= 0; inservice_r <= 0; thresh <= 0;
            for (integer s = 0; s < 8; s = s + 1) pri[s] <= 0;
        end else begin
            pending_r <= next_pending;
            inservice_r <= next_inservice;
            if (psel && pwrite) case (ridx)
                2'd0: for (integer s = 0; s < 8; s = s + 1) if (s < NS) pri[s] <= wdata[s*3 +: 3];
                2'd1: thresh <= wdata[2:0];
                default: begin end
            endcase
        end
    end
endmodule
