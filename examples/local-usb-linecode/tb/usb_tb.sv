`timescale 1ns/1ps
module usb_tb;
    parameter PKT=0, MUTATION=0;
    reg clk=0, rst_n=1, start=0;
    reg [3:0] pid=0, nbytes=0;
    reg [63:0] payload=0;
    reg [1:0] channel_mask=0;
    wire [1:0] line;
    wire busy, done, stuff_err, pid_err, crc_err, format_err;
    wire [3:0] rx_pid, length_bytes;
    wire [63:0] data;
    usb_linecode #(.PKT(PKT),.MUTATION(MUTATION)) tx_core(.*);
    usb_linecode_rx #(.PKT(PKT),.MUTATION(MUTATION)) rx_core(
        .clk(clk),.rst_n(rst_n),.line(line ^ channel_mask),.done(done),
        .stuff_err(stuff_err),.pid_err(pid_err),.crc_err(crc_err),.format_err(format_err),
        .pid(rx_pid),.length_bytes(length_bytes),.data(data));
    always #5 clk = ~clk;
    integer stream, count=0, op, a, c, d, e, completions;
    reg [63:0] b;
    reg recovering=0, saw_stuff;
    string vectors, wave;
    task tick;
        begin
            @(posedge clk); #1;
            if (done) completions=completions+1;
        end
    endtask
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label); $fatal(1,"row %0d line %b expected %h flags %b",count,line,a,
            {format_err,stuff_err,crc_err,pid_err}); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave)) $fatal(1);
        $dumpfile(wave); $dumpvars(0,usb_tb);
        stream=$fopen(vectors,"r"); if (!stream) $fatal(1);
        while (!$feof(stream)) begin
            if ($fscanf(stream,"%h %h %h %h %h %h\n",op,a,b,c,d,e) != 6) $fatal(1,"bad row");
            @(negedge clk);
            case (op)
                0: begin
                    if (busy === 1) recovering=1;
                    rst_n=0; channel_mask=0; tick(); rst_n=1;
                    if ({busy,done,line} !== 4'b0001) fail("USB_LINE");
                end
                1: begin
                    pid=a[3:0]; payload=b; nbytes=c[3:0]; start=1; tick(); start=0;
                    if ({busy,line} !== 3'b101) fail("USB_LINE");
                    saw_stuff=0; completions=0;
                end
                2: begin
                    tick();
                    if (line !== a[1:0]) begin
                        if (c==4) fail("USB_STUFF");
                        if (c==3) fail("USB_CRC");
                        fail("USB_LINE");
                    end
                    if (busy !== !d[0]) fail("USB_LINE");
                    if (c==4) saw_stuff=1;
                    channel_mask=b[1:0];
                end
                3: begin
                    tick(); channel_mask=0;
                    if (completions != 1) fail("USB_LINE");
                    if (pid_err !== d[0] || rx_pid !== a[3:0]) fail("USB_PID");
                    if (crc_err !== d[1]) fail("USB_CRC");
                    if (stuff_err !== d[2]) fail("USB_STUFF");
                    if (format_err !== d[3] || length_bytes !== c[3:0] || data !== b) fail("USB_LINE");
                    if (saw_stuff) $display("COVER line/stuff-zero");
                    if (data==0 && !crc_err) $display("COVER packet/zero");
                    if (data!=0 && !crc_err) $display("COVER packet/nonzero");
                    if ({format_err,stuff_err,crc_err,pid_err}==0) $display("COVER packet/accepted");
                    if (pid_err) $display("COVER error/pid");
                    if (crc_err) $display("COVER error/crc");
                    if (stuff_err) $display("COVER error/stuff");
                    if (format_err) $display("COVER error/eop");
                    if (recovering) begin $display("COVER reset/recovery"); recovering=0; end
                end
                4: begin
                    nbytes=c[3:0]; start=1; tick(); start=0;
                    if ({busy,line} !== 3'b001) fail("USB_LINE");
                end
                default: $fatal(1,"bad operation");
            endcase
            count=count+1;
        end
        $fclose(stream); $display("COUNT steps=%0d",count); $display("RESULT PASS checks=%0d",count); $finish;
    end
endmodule
