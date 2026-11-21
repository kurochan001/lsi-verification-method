`timescale 1ns/1ps
// DPI route: the C model runs inside the simulation, one handle per DUT instance.
// All RTL mutations are instantiated; +MUTATION selects the pair that is checked.
module dpi_tb #(
    parameter int INIT = 65535
);
    localparam int MUTATIONS = 6;
    localparam int BUFFER = 300;

    import "DPI-C" function void dpi_set_fault(input int fault);
    import "DPI-C" pure function shortint unsigned dpi_crc_step(input shortint unsigned crc,
                                                               input byte unsigned data);
    import "DPI-C" function chandle dpi_new(input int unsigned init);
    import "DPI-C" function void dpi_free(input chandle handle);
    import "DPI-C" context function int dpi_cycle(input chandle handle, input bit rst_n,
        input bit valid, input logic [7:0] data, input bit last,
        output bit done, output bit [15:0] crc, output byte unsigned length);
    import "DPI-C" function int dpi_block(input byte unsigned bytes [], input int unsigned count,
                                          input int unsigned init);
    export "DPI-C" function dpi_note_packet;

    logic clk;
    logic rst_n;
    logic [1:0] valid;
    logic [1:0] last;
    logic [7:0] data [2];
    logic [1:0] done_all [MUTATIONS];
    logic [15:0] crc_all [MUTATIONS][2];
    logic [7:0] length_all [MUTATIONS][2];

    for (genvar m = 0; m < MUTATIONS; m++) begin : mutation
        for (genvar c = 0; c < 2; c++) begin : channel
            packet_sum #(.INIT(INIT), .MUTATION(m)) dut (
                .clk(clk), .rst_n(rst_n), .valid(valid[c]), .data(data[c]), .last(last[c]),
                .done(done_all[m][c]), .crc(crc_all[m][c]), .length(length_all[m][c]));
        end
    end

    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end

    string vectors, observed, wave;
    int selected = 0, fault = 0;
    int fd, log, fields;
    int checks = 0;
    int unsigned noted = 0, noted_bytes = 0;
    int unsigned packets [2] = '{0, 0};
    int unsigned expected_bytes = 0;
    chandle model [2];
    bit expect_done [2];
    bit [15:0] expect_crc [2];
    byte unsigned expect_length [2];
    shortint unsigned folded [2];
    int unsigned fill [2];
    byte unsigned bytes0 [BUFFER];
    byte unsigned bytes1 [BUFFER];
    byte unsigned known [9] = '{8'h31, 8'h32, 8'h33, 8'h34, 8'h35, 8'h36, 8'h37, 8'h38, 8'h39};
    logic row_rst, valid0, valid1, last0, last1;
    logic [7:0] data0, data1;
    logic [1:0] row_valid, row_last;
    logic [7:0] row_data [2];
    int unknown, block;

    function void dpi_note_packet(input int unsigned length);
        noted++;
        noted_bytes += length;
    endfunction

    task automatic fail(input string label);
        $display("CHECK_FAIL %s", label);
        $fatal(1, "row=%0d", checks);
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s", vectors) || !$value$plusargs("OBSERVED=%s", observed))
            $fatal(1, "arguments required");
        void'($value$plusargs("MUTATION=%d", selected));
        void'($value$plusargs("MODEL_FAULT=%d", fault));
        if (selected < 0 || selected >= MUTATIONS) $fatal(1, "bad mutation");
        if ($value$plusargs("WAVE=%s", wave)) begin
            $dumpfile(wave);
            $dumpvars(0, dpi_tb);
        end
        rst_n = 0;
        valid = '0;
        last = '0;
        fd = $fopen(vectors, "r");
        log = $fopen(observed, "w");
        if (fd == 0 || log == 0) $fatal(1, "files");
        dpi_set_fault(fault);
        // Open array, second size: the published check value of the nine ASCII digits.
        block = dpi_block(known, 9, INIT);
        if ((INIT == 65535 && block != 'h29b1) || (INIT == 0 && block != 'h31c3)) fail("SUM_KNOWN");
        for (int c = 0; c < 2; c++) begin
            model[c] = dpi_new(INIT);
            folded[c] = 16'(INIT);
            fill[c] = 0;
            data[c] = '0;
        end
        while (!$feof(fd)) begin
            // Scalars and whole variables only: Verilator 5.052 emits invalid C++ for a
            // $fscanf target that is a bit select of a vector.
            fields = $fscanf(fd, "%b %b %b %b %b %b %b\n", row_rst, valid0, data0, last0, valid1, data1, last1);
            if (fields != 7) $fatal(1, "bad row");
            row_valid = {valid1, valid0};
            row_last = {last1, last0};
            row_data[0] = data0;
            row_data[1] = data1;
            @(negedge clk);
            rst_n = row_rst;
            valid = row_valid;
            last = row_last;
            data[0] = row_data[0];
            data[1] = row_data[1];
            for (int c = 0; c < 2; c++) begin
                unknown = dpi_cycle(model[c], row_rst, row_valid[c], row_data[c], row_last[c],
                                    expect_done[c], expect_crc[c], expect_length[c]);
                if (row_rst && row_valid[c] && unknown != 0) fail("SUM_X_INPUT");
                if (!row_rst) begin
                    folded[c] = 16'(INIT);
                    fill[c] = 0;
                end else if (row_valid[c]) begin
                    folded[c] = dpi_crc_step(folded[c], row_data[c]);
                    if (fill[c] < BUFFER) begin
                        if (c == 0) bytes0[fill[c]] = row_data[c];
                        else bytes1[fill[c]] = row_data[c];
                    end
                    fill[c]++;
                    if (row_last[c]) begin
                        packets[c]++;
                        expected_bytes += 32'(expect_length[c]);
                        if (folded[c] != expect_crc[c]) fail("SUM_PURE");
                        if (fill[c] <= BUFFER) begin
                            block = c == 0 ? dpi_block(bytes0, fill[c], INIT) : dpi_block(bytes1, fill[c], INIT);
                            if (block != int'(expect_crc[c])) fail("SUM_BLOCK");
                        end
                        folded[c] = 16'(INIT);
                        fill[c] = 0;
                    end
                end
            end
            @(posedge clk);
            #1;
            $fdisplay(log, "%b %h %h %b %h %h", done_all[selected][0], crc_all[selected][0],
                      length_all[selected][0], done_all[selected][1], crc_all[selected][1],
                      length_all[selected][1]);
            for (int c = 0; c < 2; c++) begin
                if ($isunknown({done_all[selected][c], crc_all[selected][c], length_all[selected][c]}))
                    fail("SUM_X_OUTPUT");
                if (done_all[selected][c] !== expect_done[c]) fail("SUM_DONE");
                if (length_all[selected][c] !== expect_length[c]) fail("SUM_LEN");
                if (crc_all[selected][c] !== expect_crc[c]) fail("SUM_CRC");
            end
            checks++;
        end
        if (noted != packets[0] + packets[1] || noted_bytes != expected_bytes) fail("SUM_EXPORT");
        dpi_free(model[0]);
        if (model[1] != model[0]) dpi_free(model[1]);
        $fclose(log);
        $display("COUNT packets0=%0d", packets[0]);
        $display("COUNT packets1=%0d", packets[1]);
        $display("COUNT noted=%0d", noted);
        $display("RESULT PASS checks=%0d", checks);
        $finish;
    end
endmodule
