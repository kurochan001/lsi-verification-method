`timescale 1ns/1ps
module cdc_handshake_tb;
    parameter SYNC_STAGES=2, MUTATION=0;
    reg src_clk=0, dst_clk=0, rst_n=1, src_valid=0, dst_ready=0, src_pulse=0;
    reg [7:0] src_data=0;
    wire src_ready, dst_valid, dst_pulse, dst_rst_n;
    wire [7:0] dst_data;
    cdc_handshake #(.SYNC_STAGES(SYNC_STAGES), .MUTATION(MUTATION)) dut(
        .src_clk(src_clk), .dst_clk(dst_clk), .rst_n(rst_n),
        .src_valid(src_valid), .src_data(src_data), .src_ready(src_ready),
        .dst_ready(dst_ready), .dst_valid(dst_valid), .dst_data(dst_data),
        .src_pulse(src_pulse), .dst_pulse(dst_pulse), .dst_rst_n(dst_rst_n));
    integer fd, n, checks=0, profile, last_pulse=-1000;
    integer accepted=0, delivered=0, discarded=0, queued=0, pulse_pending=0;
    reg [7:0] queued_data;
    reg prev_sc=0, prev_dc=0, srise, drise;
    reg [63:0] v[0:12];
    reg completed=0, recovering=0, reset_pulse=0, prev_req=0, prev_ack=0;
    reg pre_ready=0, pre_valid=0, pre_pulse=0;
    reg [7:0] pre_data=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "tick=%0d src_ready=%b dst_valid=%b data=%h pulse=%b rst=%b", checks, src_ready, dst_valid, dst_data, dst_pulse, dst_rst_n); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, cdc_handshake_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12]);
            if (n != 13) $fatal(1, "bad row");
            pre_ready = src_ready; pre_valid = dst_valid; pre_data = dst_data; pre_pulse = dst_pulse;
            srise=v[0][0] && !prev_sc; drise=v[1][0] && !prev_dc;
            src_clk = v[0][0]; dst_clk = v[1][0]; rst_n = v[2][0];
            src_valid = v[3][0]; src_data = v[4][7:0]; dst_ready = v[5][0];
            src_pulse = v[6][0]; profile = v[7][1:0];
            #1;
            if (dst_rst_n !== v[12][0]) fail("CDC_RESET");
            if (src_ready !== v[8][0]) fail("CDC_READY");
            if (dst_valid !== v[9][0]) fail("CDC_VALID");
            if (dst_valid && dst_data !== v[10][7:0]) fail("CDC_DATA");
            if (dst_pulse !== v[11][0]) fail("CDC_PULSE");
            if (!rst_n) begin
                if (prev_req || prev_ack) $display("COVER handshake/reset-during-request");
                recovering = 1; reset_pulse = 1; completed=0;
                discarded=discarded+queued; queued=0; pulse_pending=0; last_pulse=-1000;
            end else begin
                if (srise && src_valid && pre_ready) begin
                    if (queued!=0) fail("CDC_QUEUE");
                    queued=1; queued_data=src_data; accepted=accepted+1;
                    $display("COVER handshake/single");
                    $display("COVER clock/profile%0d", profile);
                    if (completed) begin $display("COVER handshake/back-to-back"); completed = 0; end
                    if (recovering) begin $display("COVER handshake/recovery"); recovering = 0; end
                end
                if (drise && pre_valid && !dst_ready) $display("COVER handshake/backpressure");
                if (drise && pre_valid && dst_ready) completed = 1;
                if (drise && pre_valid && dst_ready) begin
                    if (queued!=1 || pre_data!==queued_data) fail("CDC_QUEUE");
                    queued=0; delivered=delivered+1;
                    if (pre_data == 8'h00) $display("COVER data/zero");
                    if (pre_data == 8'hff) $display("COVER data/ones");
                    if (pre_data == 8'h55 || pre_data == 8'haa) $display("COVER data/alternating");
                end
                if (srise && src_pulse) pulse_pending=pulse_pending+1;
                if (drise && pre_pulse) begin
                    if (pulse_pending==0) fail("CDC_PULSE_COUNT");
                    pulse_pending=pulse_pending-1;
                    $display("COVER pulse/single");
                    if (checks - last_pulse < 60) $display("COVER pulse/back-to-back");
                    if (reset_pulse) begin $display("COVER pulse/reset"); reset_pulse = 0; end
                    last_pulse = checks;
                end
            end
            prev_sc=src_clk; prev_dc=dst_clk;
            prev_req = dut.req; prev_ack = dut.ack;
            checks = checks + 1;
            #1;
        end
        $fclose(fd);
        if (queued!=0 || accepted!=delivered+discarded || pulse_pending!=0) fail("CDC_DRAIN");
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
