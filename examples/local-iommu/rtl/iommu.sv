module iommu #(parameter TLB=1, MUTATION=0)(
    input wire clk, rst_n,
    input wire req_valid,
    input wire [1:0] req_vpn,
    input wire req_write,
    input wire tup_valid,
    input wire [2:0] tup_sel,
    input wire [1:0] tup_vpn,
    input wire [3:0] tup_pfn,
    input wire tup_wr,
    input wire tup_valid_bit,
    output wire busy, gnt,
    output wire [3:0] pfn,
    output wire [1:0] fault,
    output wire [7:0] tlb_vpn, tlb_valid
);
    // 4 table entries (valid, vpn tag, pfn, writable).  A table miss takes a
    // 2-cycle walk; a TLB hit answers next cycle.  A table update invalidates
    // matching TLB slots so a stale hit is impossible, and it never rewrites a
    // response that was already registered.  While the walk runs the request
    // is held (backpressure) and answered afterwards.  MUTATION:
    // 1 = TLB hit ignores writable, 2 = update skips the invalidate,
    // 3 = the walk ends after one cycle, 4 = the walk uses invalid entries.
    reg [3:0] tab_pfn [0:3];
    reg [1:0] tab_vpn [0:3];
    reg tab_v [0:3], tab_wr [0:3];
    reg [3:0] tlb_pfn [0:3];
    reg [1:0] tlb_evpn [0:3];
    reg tlb_v [0:3], tlb_wr [0:3];
    reg [1:0] rr;
    reg busy_r, hvalid, hwrite;
    reg [1:0] hvpn;
    reg [1:0] cnt;
    reg rsp_v;
    reg [3:0] rsp_pfn;
    reg [1:0] rsp_fault;
    reg [3:0] q_pfn;
    reg [1:0] q_fault;
    reg [3:0] n_pfn;
    reg n_wr;
    reg [1:0] n_fault;
    reg hit, do_done, do_hit, rsp_next;
    reg n_found;
    reg [3:0] hit_pfn;
    reg hit_wr;
    wire filled = do_done && n_fault != 2'd1;
    wire [1:0] old_vpn = tab_vpn[tup_sel[1:0]];
    wire [1:0] nslot = rr == 2'(TLB - 1) ? 2'd0 : rr + 2'd1;

    always @* begin
        hit = 0; hit_pfn = 0; hit_wr = 0;
        for (integer i = 0; i < 4; i = i + 1)
            if (!hit && i < TLB && tlb_v[i] && tlb_evpn[i] == req_vpn) begin
                hit = 1; hit_pfn = tlb_pfn[i]; hit_wr = tlb_wr[i];
            end
    end

    always @* begin
        n_pfn = 0; n_wr = 0; n_fault = 2'd1; n_found = 0;
        for (integer i = 0; i < 4; i = i + 1)
            if (!n_found && (MUTATION == 4 || tab_v[i]) && tab_vpn[i] == hvpn) begin
                n_found = 1;
                n_pfn = tab_pfn[i]; n_wr = tab_wr[i];
                n_fault = (hwrite && !tab_wr[i]) ? 2'd2 : 2'd0;
            end
    end

    always @* begin
        do_done = busy_r && hvalid && (MUTATION == 3 ? cnt == 2'd2 : cnt == 2'd1);
        do_hit = !busy_r && req_valid && hit;
        rsp_next = do_done || do_hit;
        rsp_pfn = 0; rsp_fault = 2'd1;
        if (do_done) begin
            rsp_pfn = n_pfn; rsp_fault = n_fault;
        end else if (do_hit) begin
            rsp_pfn = hit_pfn;
            rsp_fault = MUTATION == 1 ? 2'd0 : (req_write && !hit_wr) ? 2'd2 : 2'd0;
        end
    end

    assign busy = busy_r;
    assign gnt = rsp_v;
    assign pfn = rsp_v ? q_pfn : 4'h0;
    assign fault = rsp_v ? q_fault : 2'b00;
    assign tlb_vpn = {tlb_evpn[3], tlb_evpn[2], tlb_evpn[1], tlb_evpn[0]};
    assign tlb_valid = {4'b0000, tlb_v[3], tlb_v[2], tlb_v[1], tlb_v[0]};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy_r <= 0; hvalid <= 0; hwrite <= 0; hvpn <= 0; cnt <= 0; rr <= 0;
            rsp_v <= 0; q_pfn <= 0; q_fault <= 0;
            for (integer i = 0; i < 4; i = i + 1) begin
                tab_v[i] <= 0; tab_wr[i] <= 0; tab_vpn[i] <= 0; tab_pfn[i] <= 0;
                tlb_v[i] <= 0; tlb_wr[i] <= 0; tlb_evpn[i] <= 0; tlb_pfn[i] <= 0;
            end
        end else begin
            if (do_done) begin
                busy_r <= 0; hvalid <= 0;
                if (n_fault != 2'd1) begin
                    tlb_v[rr] <= 1; tlb_evpn[rr] <= hvpn;
                    tlb_pfn[rr] <= n_pfn; tlb_wr[rr] <= n_wr;
                    rr <= nslot;
                end
            end
            if (!busy_r && !do_done && req_valid && !hit) begin
                busy_r <= 1; cnt <= 2'd2;
                hvalid <= 1; hvpn <= req_vpn; hwrite <= req_write;
            end
            if (busy_r && !do_done)
                cnt <= cnt - 2'd1;
            rsp_v <= rsp_next; q_pfn <= rsp_pfn; q_fault <= rsp_fault;
            if (tup_valid && tup_sel < 4) begin
                tab_v[tup_sel[1:0]] <= tup_valid_bit; tab_vpn[tup_sel[1:0]] <= tup_vpn;
                tab_pfn[tup_sel[1:0]] <= tup_pfn; tab_wr[tup_sel[1:0]] <= tup_wr;
                if (MUTATION != 2)
                    for (integer i = 0; i < 4; i = i + 1) begin
                        // An update examines the replacement tag if this edge
                        // also filled the slot. The already-issued response stands.
                        if (filled && i[1:0] == rr) begin
                            if (hvpn == tup_vpn || hvpn == old_vpn)
                                tlb_v[i] <= 0;
                        end else if (tlb_v[i] && (tlb_evpn[i] == tup_vpn || tlb_evpn[i] == old_vpn))
                            tlb_v[i] <= 0;
                    end
            end
        end
    end
endmodule
