`timescale 1ns/1ps
module plic_tb;
    parameter NS=4, MUTATION=0;
    reg clk=0, rst_n=1, psel=0, pwrite=0;
    reg [1:0] ridx=0;
    reg [31:0] wdata=0;
    reg [7:0] set=0;
    wire [31:0] rdata;
    wire [7:0] pending, inservice, cand_ge;
    wire [3:0] pick;
    wire irq;
    plic #(.NS(NS), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .psel(psel), .pwrite(pwrite), .ridx(ridx),
        .wdata(wdata), .set(set), .rdata(rdata), .pending(pending),
        .inservice(inservice), .cand_ge(cand_ge), .pick(pick), .irq(irq));
    always #5 clk = ~clk;
    integer fd, n, checks=0;
    reg [63:0] v[0:9];
    reg recovering=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d psel=%b we=%b ridx=%0d wdata=%h set=%h rdata=%h exp=%h irq=%b pen=%b ins=%b", checks, psel, pwrite, ridx, wdata, set, rdata, v[6][31:0], irq, pending, inservice); end
    endtask
    wire claim_read = psel && !pwrite && ridx == 2'd2;
    wire [7:0] pick_bit = (claim_read && pick != 0) ? (8'h01 << (pick - 4'd1)) : 8'h00;
    wire [3:0] cid = wdata[3:0];
    wire complete_ok = psel && pwrite && ridx == 2'd3 &&
        wdata != 0 && wdata <= NS && ((inservice >> (cid - 4'd1)) & 8'h01) != 0;
    reg [23:0] programmed_priorities = 0;
    integer other;
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, plic_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9]);
            if (n != 10) $fatal(1, "bad row");
            rst_n = v[0][0]; psel = v[1][0]; pwrite = v[2][0]; ridx = v[3][1:0];
            wdata = v[4][31:0]; set = v[5][7:0];
            #1;
            if (pending !== v[8][7:0]) fail("PLIC_STATE");
            if (inservice !== v[9][7:0]) fail("PLIC_STATE");
            if (irq !== v[7][0]) fail("PLIC_IRQ");
            if (rdata !== v[6][31:0]) fail("PLIC_CLAIM");
            if (irq) $display("COVER irq/line");
            if (set && !claim_read) $display("COVER state/pending-set");
            if (claim_read && rdata != 0) begin
                $display("COVER claim/grant");
                for (other = 0; other < NS; other = other + 1)
                    if (cand_ge[other] && !pick_bit[other] &&
                        programmed_priorities[3*other +: 3] == programmed_priorities[3*(pick-1) +: 3])
                        $display("COVER claim/tie");
                if (inservice != 0) $display("COVER state/inservice-hold");
                if ((set & pick_bit) != 0) $display("COVER state/repending");
            end
            if (claim_read && rdata == 0) begin
                $display("COVER claim/deny");
                if ((pending & ~inservice) != 0) $display("COVER claim/none-while-pending");
            end
            if (complete_ok) $display("COVER complete/release");
            if (psel && pwrite && ridx == 2'd3 && !complete_ok) $display("COVER complete/ignore");
            if (psel && !pwrite && ridx == 2'd0 && rdata != 0) $display("COVER priority/pack-read");
            if (!rst_n) begin
                recovering = 1;
            end else if (psel) begin
                if (recovering) begin $display("COVER reset/recovery"); recovering = 0; end
            end
            if (!rst_n) programmed_priorities = 0;
            else if (psel && pwrite && ridx == 0) programmed_priorities = wdata[23:0];
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
