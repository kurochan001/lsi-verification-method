`timescale 1ns/1ps
// Drives sar_logic from a vector file and checks every pin on every clock.
//
// CMP_EXT = 0: the comparator is the real-number model, closed around the logic.
// CMP_EXT = 1: the comparator answers come from the vector file (decisions made by ngspice),
//              so the same logic is checked against the codes it was assumed to present.
module sar_adc_tb;
    parameter integer BITS = 6;
    parameter integer MUTATION = 0;
    parameter integer CMP_EXT = 0;

    reg clk = 0;
    always #5 clk = ~clk;

    reg rst_n = 0, start = 0, cmp_ext = 0;
    reg signed [31:0] vin_uv = 0;
    wire start_ready, sample, busy, done, cmp_rnm;
    wire [BITS-1:0] dac_code, result;
    wire cmp = CMP_EXT != 0 ? cmp_ext : cmp_rnm;

    sar_logic #(.BITS(BITS), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .start(start), .cmp(cmp), .start_ready(start_ready),
        .sample(sample), .dac_code(dac_code), .busy(busy), .done(done), .result(result));
    sar_cdac_rnm #(.BITS(BITS)) analog(.sample(sample), .dac_code(dac_code), .cmp(cmp_rnm));

    string vector_path, trace_path, wave_path;
    integer input_fd, output_fd, fields, cycles = 0, planned;
    reg [31:0] row [0:12];
    reg seen_keep = 0, seen_drop = 0;
    integer top_nv;

    task fail(input string label);
        begin
            $display("CHECK_FAIL %s", label);
            $fatal(1, "cycle %0d", cycles);
        end
    endtask

    always @* analog.vin_v = $itor(vin_uv) * 1.0e-6;

    initial begin
        if (!$value$plusargs("VECTORS=%s", vector_path) ||
            !$value$plusargs("CSV=%s", trace_path) ||
            !$value$plusargs("CHECKS=%d", planned))
            $fatal(1, "missing run arguments");
        if ($value$plusargs("WAVE=%s", wave_path)) begin
            $dumpfile(wave_path);
            $dumpvars(0, sar_adc_tb);
        end
        input_fd = $fopen(vector_path, "r");
        output_fd = $fopen(trace_path, "w");
        if (!input_fd || !output_fd) $fatal(1, "cannot open run files");
        $fdisplay(output_fd, "cycle,ready,sample,dac,busy,done,result,cmp,top_nv");
        while (!$feof(input_fd)) begin
            fields = $fscanf(input_fd, "%h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9],
                row[10], row[11], row[12]);
            if (fields != 13) $fatal(1, "bad vector row");
            if (row[0] == 0) begin
                // Analogue value: index 0..BITS is an array element (attofarads), ff the
                // parasitic, fe the reference in microvolts.
                if (row[1] == 32'hff) analog.cp = $itor(row[2]);
                else if (row[1] == 32'hfe) analog.vref_v = $itor(row[2]) * 1.0e-6;
                else if (row[1] <= BITS) analog.cap[row[1]] = $itor(row[2]);
                else $fatal(1, "capacitor index out of range");
            end else begin
                @(negedge clk);
                rst_n = row[1][0];
                start = row[2][0];
                vin_uv = row[3];
                cmp_ext = row[4][0];
                @(posedge clk);
                #1;
                if (^{start_ready, sample, dac_code, busy, done, result, cmp} === 1'bx)
                    fail("SAR_UNKNOWN");
                if (start_ready !== row[5][0]) fail("SAR_READY");
                if (sample !== row[6][0]) fail("SAR_SAMPLE");
                if (busy !== row[8][0]) fail("SAR_BUSY");
                if (dac_code !== row[7][BITS-1:0]) fail("SAR_DAC");
                if (done !== row[9][0]) fail("SAR_DONE");
                if (result !== row[10][BITS-1:0]) fail("SAR_RESULT");
                if (CMP_EXT == 0 && row[12][0] && cmp_rnm !== row[11][0]) fail("RNM_CMP");
                top_nv = $rtoi(analog.top_v * 1.0e9 + (analog.top_v < 0.0 ? -0.5 : 0.5));
                $fdisplay(output_fd, "%0d,%b,%b,%0d,%b,%b,%0d,%b,%0d", cycles, start_ready,
                    sample, dac_code, busy, done, result, cmp, top_nv);
                if (row[12][0] && row[11][0]) seen_keep = 1;
                if (row[12][0] && !row[11][0]) seen_drop = 1;
                cycles = cycles + 1;
            end
        end
        if (cycles != planned) $fatal(1, "completion count differs");
        $fclose(input_fd);
        $fclose(output_fd);
        if (CMP_EXT == 0 && seen_keep) $display("COVER rnm/threshold-above");
        if (CMP_EXT == 0 && seen_drop) $display("COVER rnm/threshold-below");
        $display("COUNT steps=%0d", cycles);
        $display("RESULT PASS checks=%0d", cycles);
        $finish;
    end
endmodule
