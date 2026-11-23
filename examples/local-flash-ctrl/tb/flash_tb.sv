`timescale 1ns/1ps
module flash_tb;
    parameter DIV=1, MUTATION=0;
    reg clk=0, rst_n=1, go=0, xip=0, stuck=0;
    reg [7:0] opcode=0, addr=0, wdata=0;
    wire done, err, wel, wip, sclk, csb, mosi, device_so, device_wel;
    wire [7:0] rdata, q;
    flash_ctrl #(.DIV(DIV), .MUTATION(MUTATION)) dut (
        .clk(clk), .rst_n(rst_n), .go(go), .opcode(opcode), .addr(addr), .wdata(wdata),
        .xip(xip), .done(done), .err(err), .wel(wel), .wip(wip), .rdata(rdata),
        .spi_sclk(sclk), .spi_csb(csb), .spi_mosi(mosi),
        .spi_miso(stuck || device_so), .flash_q(q));
    flash_model #(.DIV(DIV)) device (
        .clk(clk), .rst_n(rst_n), .csb(csb), .sclk(sclk), .mosi(mosi),
        .xip_en(xip), .xip_addr(addr), .q(q), .miso(device_so), .wel(device_wel), .wip());
    always #5 clk = ~clk;
    integer fd, fields, checked=0, i, half_tick, samples, sample_tick;
    reg [31:0] kind, op, index, data, hold_busy, bytes, packet, exp_err, exp_byte,
               exp_wel, busy_samples, exp_wip;
    reg sampled_so;
    string vectors, wave;
    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "row=%0d op=%h addr=%h csb=%b sclk=%b mosi=%b done=%b err=%b wel=%b wip=%b read=%h",
                   checked, op, index, csb, sclk, mosi, done, err, wel, wip, rdata);
        end
    endtask

    task check_response;
        begin
            if ({done,err,csb,sclk} !== {!exp_err[0],exp_err[0],2'b10}) fail("FLASH_CTRL");
            if ({wel,wip} !== {exp_wel[0],exp_wip[0]}) fail("FLASH_STATE");
            if (rdata !== exp_byte[7:0]) fail("FLASH_DATA");
        end
    endtask

    task check_frame;
        begin
            // Enter the read window and change host pins during the transfer.
            // A selected command must use its latched address and data throughout.
            go = 0; xip = 1; opcode = 8'hff; addr = ~index[7:0]; wdata = ~data[7:0];
            #1;
            for (i=8*bytes-1; i>=0; i=i-1) begin
                for (half_tick=0; half_tick<2*DIV; half_tick=half_tick+1) begin
                    // Drive a different request for the second bit. The controller is busy.
                    go = (i == 8*bytes-2);
                    xip = !go;
                    #1;
                    if (half_tick == DIV-1) sampled_so = device_so;
                    if (half_tick >= DIV && device_so !== sampled_so) fail("FLASH_DATA");
                    if (csb !== 0 || sclk !== (half_tick >= DIV) || done !== 0 || err !== 0)
                        fail("FLASH_CTRL");
                    if (mosi !== packet[i]) fail("FLASH_DATA");
                    if (rdata !== 8'hff) fail("FLASH_DATA");
                    @(negedge clk);
                end
            end
            xip = 0; go = 0;
            #1;
        end
    endtask

    task check_poll;
        begin
            // One idle-CS clock commits the preceding frame. The device drives
            // status while selected with SCLK parked low.
            if ({csb,sclk,done,err} !== 4'b1000) fail("FLASH_CTRL");
            @(negedge clk);
            samples = busy_samples + (busy_samples < 7);
            for (i=1; i<=samples; i=i+1) begin
                for (sample_tick=0; sample_tick<2*DIV; sample_tick=sample_tick+1) begin
                    if ({csb,sclk,done,err} !== 4'b0000) fail("FLASH_CTRL");
                    @(negedge clk);
                end
                // Check early termination before checking the sampled status.
                if (i < samples && {csb,done,err} !== 3'b000) fail("FLASH_CTRL");
                if (wip !== (i <= busy_samples)) fail("FLASH_STATE");
            end
        end
    endtask

    task test_command;
        begin
            opcode = op; addr = index; wdata = data; xip = 0; go = 1; stuck = hold_busy;
            @(negedge clk);
            go = 0;
            if (bytes != 0) begin
                check_frame();
                if (op != 8'h03 && op != 8'h06) check_poll();
            end
            check_response();
            if (bytes == 0 && op == 8'h9f) $display("COVER cmd/reject");
            if (bytes == 0 && op == 8'ha0 && err && !wel) $display("COVER cmd/wel-gate");
            if (op == 8'h06 && done && wel) $display("COVER cmd/wren");
            if (op == 8'ha0 && done) $display("COVER data/program");
            if (op == 8'h03 && done) $display("COVER data/read");
            if (op == 8'h32 && done) $display("COVER erase/sector");
            if (op == 8'hd8 && done) $display("COVER erase/all");
            if (busy_samples == 6 && done) $display("COVER poll/six-busy");
            if (hold_busy && busy_samples == 7 && err) $display("COVER poll/timeout");
            if (op == 8'ha0 && !hold_busy && busy_samples == 7 && err) $display("COVER data/program-fault");
            if (op == 8'hc7 && busy_samples == 4 && done) $display("COVER poll/clear");
            stuck = 0;
            @(negedge clk);
            if (done !== 0 || err !== 0 || !csb) fail("FLASH_CTRL");
            if (device_wel !== exp_wel[0]) fail("FLASH_STATE");
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))
            $fatal(1, "VECTORS and WAVE required");
        $dumpfile(wave); $dumpvars(0,flash_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1,"vectors missing");
        @(negedge clk);
        while (!$feof(fd)) begin
            fields = $fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",
                kind,op,index,data,hold_busy,bytes,packet,exp_err,exp_byte,exp_wel,busy_samples,exp_wip);
            if (fields != 12) $fatal(1,"bad row");
            case (kind)
                0,3: begin
                    if (kind == 3) begin
                        xip = 0; go = 1; opcode = 8'h03;
                        @(negedge clk); go = 0;
                        repeat (DIV) @(negedge clk);
                        if ({csb,sclk} !== 2'b01) fail("FLASH_CTRL");
                    end
                    rst_n = 0;
                    @(negedge clk);
                    if ({csb,sclk,done,err,wel,wip} !== 6'b100000) fail("FLASH_STATE");
                    rst_n = 1;
                    if (kind == 3) $display("COVER reset/abort");
                end
                1: test_command();
                2: begin
                    xip = 1; addr = index; opcode = op; go = 1;
                    @(negedge clk);
                    if (rdata !== exp_byte[7:0]) fail("FLASH_DATA");
                    if ({csb,sclk,done,err} !== 4'b1000) fail("FLASH_CTRL");
                    if ({wel,wip} !== {exp_wel[0],exp_wip[0]}) fail("FLASH_STATE");
                    if (index == 16) $display("COVER xip/out-of-range");
                    $display("COVER xip/interlock");
                    xip = 0; go = 0;
                end
                default: $fatal(1,"unknown row kind");
            endcase
            checked = checked + 1;
        end
        $fclose(fd);
        $display("COUNT steps=%0d",checked);
        $display("RESULT PASS checks=%0d",checked);
        $finish;
    end
endmodule
