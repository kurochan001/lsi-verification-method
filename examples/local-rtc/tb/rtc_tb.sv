`timescale 1ns/1ps
module rtc_tb;
    parameter DIV=4, MUTATION=0;
    reg clk=0, rst_n=1, wr=0;
    reg [1:0] ridx=0;
    reg [7:0] wdata=0;
    reg cap=0;
    wire [7:0] rdata;
    wire [15:0] sec_pin;
    wire [7:0] sub_pin, capture_sub;
    wire irq;
    rtc #(.DIV(DIV), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .wr(wr), .ridx(ridx), .wdata(wdata),
        .cap(cap), .rdata(rdata), .sec_pin(sec_pin), .sub_pin(sub_pin), .capture_sub(capture_sub), .irq(irq));
    always #5 clk = ~clk;
    integer fd, n, checks=0;
    reg [63:0] v[0:9];
    reg recovering=0;
    reg [7:0] tctrl=0;  // testbench shadow of CTRL, built only from write rows
    reg [15:0] psec=0;
    reg [7:0] psub=0;
    reg pirq=0, pcap=0, pw1c=0;
    reg [15:0] dsec;
    reg [7:0] dsub;
    wire [7:0] last = DIV - 1;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d wr=%b ridx=%0d wdata=%h cap=%b sec=%h sub=%0d irq=%b rdata=%h exp sec=%h sub=%0d irq=%b rdata=%h tctrl=%h", checks, wr, ridx, wdata, cap, sec_pin, sub_pin, irq, rdata, v[5][15:0], v[6][7:0], v[7][0], v[8][7:0], tctrl); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, rtc_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9]);
            if (n != 10) $fatal(1, "bad row");
            rst_n = v[0][0]; wr = v[1][0]; ridx = v[2][1:0]; wdata = v[3][7:0];
            cap = v[4][0];
            #1;
            if (capture_sub !== v[9][7:0]) fail("RTC_TIME");
            if (irq !== v[7][0]) fail("RTC_IRQ");
            if (sub_pin !== v[6][7:0]) fail("RTC_TIME");
            if (sec_pin !== v[5][15:0]) fail(tctrl[1] ? "RTC_ADJ" : "RTC_TIME");
            if (rdata !== v[8][7:0]) fail(ridx == 2'd1 ? "RTC_IRQ" : "RTC_TIME");
            dsec = sec_pin - psec;
            dsub = sub_pin - psub;
            if (tctrl[0] && sub_pin != psub) $display("COVER time/tick");
            if (psub == last && sub_pin == 8'd0) $display("COVER time/wrap-sec");
            if (wr && ridx == 2'd2 && tctrl[2]) $display("COVER time/set-load");
            if (psub == last && tctrl[0] && tctrl[2] && sec_pin == psec)
                $display("COVER time/set-freeze");
            if (irq && !pirq) $display("COVER irq/match");
            if (pw1c && pirq && !irq) $display("COVER irq/w1c-clear");
            if (irq && pw1c && !pirq) $display("COVER irq/race-win");
            if (psub == last && tctrl[0] && tctrl[1]) $display("COVER adj/enabled");
            if (psub == last && tctrl[0] && tctrl[1] && dsec == 16'd0)
                $display("COVER adj/zero-pause");
            if (psub == last && tctrl[0] && dsec == 16'd4) $display("COVER adj/max-rate");
            if (cap && !pcap) $display("COVER cap/pulse");
            if (!wr && ridx == 2'd3) $display("COVER cap/readback");
            if (!wr && ridx == 2'd1 && rdata != 8'h00) $display("COVER reg/readback");
            if (!rst_n) begin
                recovering = 1;
                tctrl = 0; psec = 0; psub = 0; pirq = 0; pcap = 0; pw1c = 0;
            end else if (recovering && wr) begin
                $display("COVER reset/recovery");
                recovering = 0;
            end
            if (wr && ridx == 2'd0) tctrl = wdata[6:0];
            pirq = irq; pcap = cap; pw1c = wr && ridx == 2'd1 && wdata[1];
            psec = sec_pin; psub = sub_pin;
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
