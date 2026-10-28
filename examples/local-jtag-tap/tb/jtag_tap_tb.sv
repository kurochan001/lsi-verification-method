`timescale 1ns/1ps
module jtag_tap_tb;
    parameter IDCODE=32'h12345679, MUTATION=0;
    reg tck=0, tms=0, tdi=0, trst_n=1;
    reg [7:0] pin_in=0;
    wire tdo;
    wire [7:0] pin_out;
    jtag_tap #(.IDCODE(IDCODE), .MUTATION(MUTATION)) dut(
        .tck(tck), .tms(tms), .tdi(tdi), .trst_n(trst_n),
        .pin_in(pin_in), .tdo(tdo), .pin_out(pin_out));
    integer fd, n, checks=0, last_ir_update=-1000;
    integer shift_dr=0, shift_ir=0;
    reg [63:0] v[0:8];
    reg prev_tck=0, recovering=0, preloaded=0;
    reg [3:0] prev_state=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s", label); $fatal(1, "tick=%0d state=%0d ir=%h tdo=%b pin=%h", checks, dut.state, dut.ir, tdo, pin_out); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("WAVE=%s", wave)) $fatal(1, "args required");
        $dumpfile(wave); $dumpvars(0, jtag_tap_tb);
        fd = $fopen(vectors, "r"); if (!fd) $fatal(1, "vectors missing");
        while (!$feof(fd)) begin
            n = $fscanf(fd, "%h %h %h %h %h %h %h %h %h\n",
                v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8]);
            if (n != 9) $fatal(1, "bad row");
            tck = v[0][0]; tms = v[1][0]; tdi = v[2][0]; trst_n = v[3][0]; pin_in = v[4][7:0];
            #1;
            if (dut.state !== v[7][3:0]) fail("JTAG_STATE");
            if (dut.ir !== v[8][3:0]) fail("JTAG_IR");
            if (tdo !== v[5][0]) fail("JTAG_TDO");
            if (pin_out !== v[6][7:0]) fail("JTAG_BOUNDARY");
            if (!trst_n) begin
                recovering = 1; shift_dr = 0; shift_ir = 0; preloaded=0;
                $display("COVER reset/tlr");
            end else begin
                if (prev_state == 0 && dut.state == 1 && recovering) begin
                    $display("COVER reset/recovery"); recovering = 0;
                end
                if (dut.state == 4 && prev_state != 4) shift_dr = 0;
                if (dut.state == 11 && prev_state != 11) shift_ir = 0;
                if (tck && !prev_tck) begin
                    if (prev_state == 11) begin
                        shift_ir = shift_ir + 1; $display("COVER ir/shift");
                        $display("COVER tdo/lsb-first");
                    end
                    if (prev_state == 4) begin
                        shift_dr = shift_dr + 1; $display("COVER tdo/lsb-first");
                        if (dut.ir == 4'b0001 && shift_dr >= 32) $display("COVER idcode/read");
                        if (dut.ir != 4'b0001 && dut.ir != 4'b0010 && dut.ir != 4'b0011 && shift_dr >= 1) $display("COVER bypass/read");
                    end
                    if (prev_state == 3 && dut.ir == 4'b0010) $display("COVER sample/capture");
                end
                if (!tck && prev_tck) begin
                    if (dut.state == 15) begin
                        $display("COVER ir/update");
                        if (checks - last_ir_update < 200) $display("COVER ir/back-to-back");
                        last_ir_update = checks;
                    end
                    if (dut.state == 8 && dut.ir == 4'b0011) begin
                        $display("COVER extest/update");
                        if (pin_out == dut.bsr) $display("COVER pin/drive");
                    end
                    if (dut.state == 8 && dut.ir == 4'b0010) begin $display("COVER preload/update"); preloaded=1; end
                    if (dut.state == 15 && dut.ir == 4'b0011 && preloaded && pin_out == dut.bsr_update) begin $display("COVER preload/drive"); preloaded=0; end
                end
                if (dut.state == 6 || dut.state == 7 || dut.state == 13 || dut.state == 14)
                    $display("COVER pause/exit2");
            end
            prev_tck = tck; prev_state = dut.state;
            checks = checks + 1;
            #1;
        end
        $fclose(fd);
        $display("COUNT steps=%0d", checks);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
