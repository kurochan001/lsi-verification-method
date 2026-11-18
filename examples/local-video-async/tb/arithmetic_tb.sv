`timescale 1ns/1ps
module arithmetic_tb;
    reg clk=0,reset_n=0,valid=0,ready=0;
    reg [57:0] data=0;
    wire [2:0] s_ready,m_valid;
    wire [57:0] key_data,csc_data;
    wire [25:0] blend_data;
    integer op=0,fd,rc,checks=0;
    reg [57:0] expected;
    string vectors;
    video_key k(clk,reset_n,1'b1,valid && op==0,s_ready[0],data,m_valid[0],ready,key_data);
    video_csc c(clk,reset_n,1'b1,valid && op==1,s_ready[1],data,m_valid[1],ready,csc_data);
    video_blend b(clk,reset_n,1'b1,valid && op==2,s_ready[2],data,m_valid[2],ready,blend_data);
    always #5 clk=~clk;
    task compare;
        reg [57:0] actual;
        begin
            actual=op==0 ? key_data:op==1 ? csc_data:{32'd0,blend_data};
            if (m_valid[op]!==1'b1 || actual!==expected) begin
                $display("CHECK_FAIL ARITHMETIC row=%0d op=%0d input=%h expected=%h actual=%h",checks,op,data,expected,actual);
                $fatal(1,"arithmetic mismatch");
            end
        end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"VECTORS required");
        fd=$fopen(vectors,"r");if (!fd) $fatal(1,"cannot open arithmetic vectors");
        repeat (2) @(negedge clk);reset_n=1;
        while (!$feof(fd)) begin
            @(negedge clk);
            rc=$fscanf(fd,"%d %h %h\n",op,data,expected);
            if (rc!=3 || op<0 || op>2) $fatal(1,"bad arithmetic vector");
            valid=1;ready=0;
            @(posedge clk);if (s_ready[op]!==1'b1) $fatal(1,"arithmetic input blocked");
            #1;compare();
            @(negedge clk);valid=0;
            repeat (3) begin @(posedge clk);#1;compare();end
            @(negedge clk);ready=1;
            @(posedge clk);compare();
            @(negedge clk);ready=0;checks=checks+1;
        end
        if (checks==0) $fatal(1,"no arithmetic checks");
        $display("RESULT PASS checks=%0d",checks);$fclose(fd);$finish;
    end
    initial begin #1000000;$fatal(1,"arithmetic watchdog expired");end
endmodule
