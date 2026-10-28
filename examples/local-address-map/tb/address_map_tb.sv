`timescale 1ns/1ps
module address_map_tb;
    parameter ALIAS=1, MUTATION=0;
    reg clk=0, rst_n=1, psel=0, pwrite=0;
    reg [11:0] paddr=0;
    reg [31:0] pwdata=0;
    reg [3:0] pstrb=0, gpio_in=0;
    wire [31:0] prdata;
    wire pready, pslverr;
    wire [1:0] irq;
    wire [3:0] gpio_out;
    address_map #(.ALIAS(ALIAS), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .psel(psel), .pwrite(pwrite), .paddr(paddr),
        .pwdata(pwdata), .pstrb(pstrb), .gpio_in(gpio_in), .prdata(prdata),
        .pready(pready), .pslverr(pslverr), .irq(irq), .gpio_out(gpio_out));
    always #5 clk = ~clk;
    integer fd, n, checks=0;
    reg [63:0] v[0:11];
    reg recovering=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "step=%0d addr=%h sel=%b we=%b err=%b data=%h irq=%b", checks, paddr, psel, pwrite, pslverr, prdata, irq); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, address_map_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        repeat (2) @(negedge clk);
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11]);
            if (n != 12) $fatal(1, "bad row");
            rst_n = v[0][0]; psel = v[1][0]; pwrite = v[2][0]; paddr = v[3][11:0];
            pwdata = v[4][31:0]; pstrb = v[5][3:0]; gpio_in = v[6][3:0];
            #1;
            if (pslverr !== v[8][0]) fail("MAP_DECODE");
            if (prdata !== v[7][31:0]) fail("MAP_DATA");
            if (irq !== v[10][1:0]) fail("MAP_IRQ");
            if (gpio_out !== v[11][3:0]) fail("MAP_GPIO");
            if (pready !== v[9][0]) fail("MAP_DECODE");
            if (!rst_n) begin
                recovering = 1;
            end else if (psel) begin
                if (!pslverr && (paddr[11:8] == 0 || paddr[11:8] == 4)) $display("COVER decode/ram");
                if (!pslverr && paddr[11:8] == 1) $display("COVER decode/timer");
                if (!pslverr && paddr[11:8] == 2) $display("COVER decode/gpio");
                if (pslverr && paddr[11:8] == 3) $display("COVER decode/unmapped");
                if (paddr[11:8] == 4) $display("COVER decode/alias-check");
                if (!pslverr && pwrite && (paddr[11:8] == 0 || paddr[11:8] == 4) && pstrb != 4'hf)
                    $display("COVER bus/byte-strobe");
                if (pslverr && pwrite && pstrb != 4'hf && (paddr[11:8] == 1 || paddr[11:8] == 2))
                    $display("COVER bus/partial-reject");
                if (irq[0]) $display("COVER irq/timer");
                if (irq[1]) $display("COVER irq/gpio");
                if (irq == 2'b11) $display("COVER irq/map");
                if (!pslverr && pwrite && pstrb == 4'hf &&
                    (paddr == 12'h10c || paddr == 12'h20c) && pwdata[0]) $display("COVER irq/w1c");
                if (pslverr && pwrite) $display("COVER sideeffect/no-write");
                if (recovering && !pslverr) begin $display("COVER reset/recovery"); recovering = 0; end
            end
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
