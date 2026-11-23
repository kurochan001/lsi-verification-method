`timescale 1ns/1ps
module canfd_tb;
    parameter RATIO=3, MUTATION=0;
    reg clk=0, rst_n=1, start=0, fd=0, brs=0;
    reg [10:0] identifier=0;
    reg [3:0] dlc=0;
    reg [511:0] payload=0;
    wire busy, bit_valid, tx, stuffed, fast;
    canfd_tx #(.RATIO(RATIO),.MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer stream, count=0, op, a,b,c, i, crc_bits;
    reg [511:0] word;
    reg recovering=0, saw_fast, saw_stuff, saw_fixed;
    string vectors, wave;
    task tick;
        begin @(posedge clk); #1; end
    endtask
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label); $fatal(1,"row %0d kind %0d tx %b expected %0d",count,b,tx,a); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave)) $fatal(1);
        $dumpfile(wave); $dumpvars(0,canfd_tb);
        stream=$fopen(vectors,"r"); if (!stream) $fatal(1);
        while (!$feof(stream)) begin
            if ($fscanf(stream,"%h %h %h %h %h\n",op,a,b,c,word) != 5) $fatal(1,"bad row");
            @(negedge clk);
            case (op)
                0: begin
                    if (busy === 1) recovering=1;
                    rst_n=0; tick();
                    if ({busy,bit_valid,tx} !== 3'b001) fail("CANFD_STREAM");
                    rst_n=1;
                end
                1: begin
                    fd=a[0]; brs=a[1]; identifier=b[10:0]; dlc=c[3:0]; payload=word;
                    start=1; tick(); start=0;
                    if ({busy,bit_valid} !== 2'b10) fail("CANFD_STREAM");
                    saw_fast=0; saw_stuff=0; saw_fixed=0; crc_bits=0;
                end
                2: begin
                    tick();
                    if ({busy,bit_valid,fast} !== {2'b11,c[0]}) fail("CANFD_STREAM");
                    if (stuffed !== (b == 1 || b == 2)) fail("CANFD_STUFF");
                    if (tx !== a[0]) begin
                        if (stuffed) fail("CANFD_STUFF");
                        if (b == 3 || b == 4) fail("CANFD_CRC");
                        fail("CANFD_STREAM");
                    end
                    if (b == 4) crc_bits=crc_bits+1;
                    saw_fast=saw_fast || fast;
                    saw_stuff=saw_stuff || b == 1;
                    saw_fixed=saw_fixed || b == 2;
                    if (!c[0]) for (i=1;i<RATIO;i=i+1) begin
                        tick();
                        if ({busy,bit_valid,tx,fast} !== {2'b10,a[0],1'b0}) fail("CANFD_STREAM");
                    end
                end
                3: begin
                    tick(); if ({busy,bit_valid,tx} !== 3'b001) fail("CANFD_STREAM");
                    if (!fd && crc_bits == 15) $display("COVER crc/classic15");
                    if (fd && dlc == 10 && crc_bits == 17) $display("COVER crc/fd16bytes");
                    if (fd && dlc == 11 && crc_bits == 21) $display("COVER crc/fd20bytes");
                    if (fd && dlc == 15 && crc_bits == 21) $display("COVER data/64bytes");
                    if (dlc == 0) $display("COVER data/empty");
                    if (saw_fast) $display("COVER rate/switch");
                    if (fd && !saw_fast) $display("COVER rate/nominal-fd");
                    if (saw_stuff) $display("COVER stuff/dynamic");
                    if (saw_fixed) $display("COVER stuff/fixed");
                    if (recovering) begin $display("COVER reset/recovery"); recovering=0; end
                end
                default: $fatal(1,"bad operation");
            endcase
            count=count+1;
        end
        $fclose(stream); $display("COUNT steps=%0d",count); $display("RESULT PASS checks=%0d",count); $finish;
    end
endmodule
