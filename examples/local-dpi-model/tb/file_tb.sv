`timescale 1ns/1ps
// File route for simulators without DPI: the C model has already written the expected
// outputs of every clock to a file. Stimulus, sampling points and labels match dpi_tb.
module file_tb #(
    parameter INIT = 65535,
    parameter MUTATION = 0
);
    reg clk = 0;
    reg rst_n = 0;
    reg [1:0] valid = 0;
    reg [1:0] last = 0;
    reg [7:0] data0 = 0;
    reg [7:0] data1 = 0;
    wire [1:0] done;
    wire [15:0] crc0, crc1;
    wire [7:0] length0, length1;

    packet_sum #(.INIT(INIT), .MUTATION(MUTATION)) dut0 (
        .clk(clk), .rst_n(rst_n), .valid(valid[0]), .data(data0), .last(last[0]),
        .done(done[0]), .crc(crc0), .length(length0));
    packet_sum #(.INIT(INIT), .MUTATION(MUTATION)) dut1 (
        .clk(clk), .rst_n(rst_n), .valid(valid[1]), .data(data1), .last(last[1]),
        .done(done[1]), .crc(crc1), .length(length1));

    always #5 clk = ~clk;

    reg [8*1024-1:0] vectors, expected, observed, wave;
    integer fd, efd, log, fields;
    integer checks = 0;
    integer packets0 = 0, packets1 = 0;
    reg row_rst, valid0, valid1, last0, last1, done0, done1;
    reg [1:0] row_valid, row_last, expect_done;
    reg [7:0] row_data0, row_data1, expect_length0, expect_length1;
    reg [15:0] expect_crc0, expect_crc1;

    task fail(input [8*16-1:0] label);
        begin
            $display("CHECK_FAIL %0s", label);
            $fatal(1, "row=%0d", checks);
        end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("EXPECTED=%s", expected) ||
            !$value$plusargs("OBSERVED=%s", observed))
            $fatal(1, "arguments required");
        if ($value$plusargs("WAVE=%s", wave)) begin
            $dumpfile(wave);
            $dumpvars(0, file_tb);
        end
        fd = $fopen(vectors, "r");
        efd = $fopen(expected, "r");
        log = $fopen(observed, "w");
        if (!fd || !efd || !log) $fatal(1, "files");
        while (!$feof(fd)) begin
            fields = $fscanf(fd, "%b %b %b %b %b %b %b\n", row_rst, valid0, row_data0, last0, valid1, row_data1, last1);
            if (fields != 7) $fatal(1, "bad row");
            row_valid = {valid1, valid0};
            row_last = {last1, last0};
            fields = $fscanf(efd, "%b %h %h %b %h %h\n", done0, expect_crc0, expect_length0, done1, expect_crc1, expect_length1);
            expect_done = {done1, done0};
            if (fields != 6) $fatal(1, "expected file is shorter than the vectors");
            @(negedge clk);
            rst_n = row_rst;
            valid = row_valid;
            last = row_last;
            data0 = row_data0;
            data1 = row_data1;
            if (row_rst && ((row_valid[0] && ^row_data0 === 1'bx) || (row_valid[1] && ^row_data1 === 1'bx)))
                fail("SUM_X_INPUT");
            if (row_rst && row_valid[0] && row_last[0]) packets0 = packets0 + 1;
            if (row_rst && row_valid[1] && row_last[1]) packets1 = packets1 + 1;
            @(posedge clk);
            #1;
            $fdisplay(log, "%b %h %h %b %h %h", done[0], crc0, length0, done[1], crc1, length1);
            if (^{done[0], crc0, length0} === 1'bx) fail("SUM_X_OUTPUT");
            if (done[0] !== expect_done[0]) fail("SUM_DONE");
            if (length0 !== expect_length0) fail("SUM_LEN");
            if (crc0 !== expect_crc0) fail("SUM_CRC");
            if (^{done[1], crc1, length1} === 1'bx) fail("SUM_X_OUTPUT");
            if (done[1] !== expect_done[1]) fail("SUM_DONE");
            if (length1 !== expect_length1) fail("SUM_LEN");
            if (crc1 !== expect_crc1) fail("SUM_CRC");
            checks = checks + 1;
        end
        if (!$feof(efd)) $fatal(1, "expected file is longer than the vectors");
        $fclose(log);
        $display("COUNT packets0=%0d", packets0);
        $display("COUNT packets1=%0d", packets1);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
