`timescale 1ns/1ps
module iommu_tb;
    parameter TLB=1, MUTATION=0;
    reg clk=0, rst_n=1, req_valid=0, req_write=0;
    reg [1:0] req_vpn=0;
    reg tup_valid=0, tup_wr=0, tup_valid_bit=0;
    reg [2:0] tup_sel=0;
    reg [1:0] tup_vpn=0;
    reg [3:0] tup_pfn=0;
    wire busy, gnt;
    wire [3:0] pfn;
    wire [1:0] fault;
    wire [7:0] tlb_vpn, tlb_valid;
    iommu #(.TLB(TLB), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .req_valid(req_valid), .req_vpn(req_vpn),
        .req_write(req_write), .tup_valid(tup_valid), .tup_sel(tup_sel),
        .tup_vpn(tup_vpn), .tup_pfn(tup_pfn), .tup_wr(tup_wr),
        .tup_valid_bit(tup_valid_bit), .busy(busy), .gnt(gnt), .pfn(pfn),
        .fault(fault), .tlb_vpn(tlb_vpn), .tlb_valid(tlb_valid));
    always #5 clk = ~clk;
    integer fd, n, checks=0, i;
    reg [63:0] v[0:15];
    reg recovering=0;
    reg pbusy=0;
    reg [7:0] pvpn=0, pvalid=0;
    reg [3:0] invalidations=0;
    reg hit_now;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d req=%b vpn=%0d w=%b tup=%b sel=%0d busy=%b gnt=%b pfn=%h fault=%b tlbvpn=%h tlbvalid=%h exp gnt=%b pfn=%h fault=%b", checks, req_valid, req_vpn, req_write, tup_valid, tup_sel, busy, gnt, pfn, fault, tlb_vpn, tlb_valid, v[11][0], v[12][3:0], v[13][1:0]); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, iommu_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13], v[14], v[15]);
            if (n != 16) $fatal(1, "bad row");
            rst_n = v[0][0]; req_valid = v[1][0]; req_vpn = v[2][1:0]; req_write = v[3][0];
            tup_valid = v[4][0]; tup_sel = v[5][2:0]; tup_vpn = v[6][1:0];
            tup_pfn = v[7][3:0]; tup_wr = v[8][0]; tup_valid_bit = v[9][0];
            #1;
            if (gnt !== v[11][0]) fail("IOMMU_XLAT");
            if (pfn !== v[12][3:0]) fail("IOMMU_XLAT");
            if (fault !== v[13][1:0]) fail("IOMMU_FAULT");
            if (busy !== v[10][0]) fail("IOMMU_STATE");
            if (tlb_vpn !== v[14][7:0]) fail("IOMMU_STATE");
            if (tlb_valid !== v[15][7:0]) fail("IOMMU_STATE");
            hit_now = 0;
            for (i = 0; i < TLB; i = i + 1)
                if (req_valid && tlb_valid[i] && tlb_vpn[2*i +: 2] == req_vpn) hit_now = 1;
            if (gnt && fault == 2'd2) $display("COVER xlat/perm-deny");
            if (gnt && fault == 2'd1) $display("COVER xlat/miss-fault");
            if (gnt && fault == 2'd0 && hit_now) $display("COVER xlat/hit-path");
            for (i = 0; i < TLB; i = i + 1) begin
                if (!tlb_valid[i] && pvalid[i]) begin
                    $display("COVER tlb/invalidate");
                    invalidations |= 4'h1 << tlb_vpn[2*i +: 2];
                end
                if (tlb_valid[i] && !pvalid[i]) begin
                    $display("COVER tlb/fill");
                    if ((invalidations >> tlb_vpn[2*i +: 2]) & 4'h1) $display("COVER tlb/refetch");
                end
                if (tlb_valid[i] && pvalid[i] && tlb_vpn[2*i +: 2] != pvpn[2*i +: 2])
                    $display("COVER tlb/replace");
            end
            if (busy && req_valid) $display("COVER busy/hold-request");
            if (busy && req_valid && !gnt) $display("COVER busy/deny");
            if (!busy && pbusy && gnt) $display("COVER busy/complete-grant");
            if (tup_valid && tup_sel >= 3'd4) $display("COVER upd/ignore-range");
            if (tup_valid && busy) $display("COVER upd/while-busy");
            if (gnt && tup_valid) $display("COVER resp/grant-kept");
            if (!rst_n) begin
                recovering = 1;
                pvalid = 0; pvpn = 0; invalidations = 0;
            end else if (recovering && busy) begin
                $display("COVER reset/recovery");
                recovering = 0;
            end
            pvalid = tlb_valid; pvpn = tlb_vpn; pbusy = busy;
            checks = checks + 1;
            @(posedge clk); #1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
