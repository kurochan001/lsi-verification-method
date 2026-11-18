`timescale 1ns/1ps
module fifo_tb;
    parameter DEPTH=4,SAMPLES=512;
    reg wclk=0,rclk=0,arst_n=1,valid=0,ready=0;
    reg [31:0] data=0;
    wire wr_ready,rd_valid,wr_reset_n,rd_reset_n;
    wire [31:0] rd_data;
    wire [$clog2(DEPTH):0] level;
    real wp=10.0,rp=17.0,wphase=0.0,rphase=0.0;
    reg configured=0,taken=0;
    integer sent=0,received=0,wcycles=0,rcycles=0;
    string wave;
    video_reset_sync ws(wclk,arst_n,wr_reset_n);
    video_reset_sync rs(rclk,arst_n,rd_reset_n);
    video_async_fifo #(.DATA_W(32),.DEPTH(DEPTH)) dut(wclk,rclk,wr_reset_n,rd_reset_n,valid,wr_ready,data,rd_valid,ready,rd_data,level);
    video_fifo_checker #(.DATA_W(32),.DEPTH(DEPTH),.ID(3)) check_fifo(
        wclk,rclk,arst_n,wr_reset_n,rd_reset_n,valid,wr_ready,data,rd_valid,ready,rd_data,dut.wbin,dut.rbin,dut.wgray,dut.rgray);
    initial begin
        if ($value$plusargs("WP=%f",wp)) begin end
        if ($value$plusargs("RP=%f",rp)) begin end
        if ($value$plusargs("WPHASE=%f",wphase)) begin end
        if ($value$plusargs("RPHASE=%f",rphase)) begin end
        if ($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,fifo_tb);end
        configured=1;#1;arst_n=0;#100;arst_n=1;
    end
    initial begin wait(configured);#(wphase);forever #(wp/2.0) wclk=~wclk;end
    initial begin wait(configured);#(rphase);forever #(rp/2.0) rclk=~rclk;end
    always @(posedge wclk or negedge arst_n) begin
        if (!arst_n) begin sent<=0;taken<=0;wcycles<=0;end
        else begin
            wcycles<=wcycles+1;taken<=valid && wr_ready;
            if (valid && wr_ready) sent<=sent+1;
        end
    end
    always @(negedge wclk) begin
        if (!wr_reset_n) begin valid<=0;data<=0;end
        else if (!valid || taken) begin
            valid<=sent<SAMPLES && wcycles>20 && wcycles%11!=0;
            data<=32'(sent)^32'ha5f03c69;
        end
    end
    always @(negedge rclk) begin
        if (!rd_reset_n) begin ready<=0;rcycles<=0;end
        else begin rcycles<=rcycles+1;ready<=rcycles>80 && rcycles%7!=0;end
    end
    always @(posedge rclk or negedge arst_n) begin
        if (!arst_n) received<=0;
        else if (rd_valid && ready) received<=received+1;
    end
    initial begin
        wait(received==SAMPLES);repeat (8) @(posedge rclk);#2;
        if (sent!=SAMPLES || rd_valid!==1'b0 || check_fifo.full_waits==0 || check_fifo.empty_waits==0 ||
            check_fifo.full_releases==0 || check_fifo.empty_releases==0 ||
            check_fifo.written!=SAMPLES || check_fifo.read_count!=SAMPLES) $fatal(1,"FIFO completion or boundary coverage missing");
        $display("COUNT writes=%0d",sent);$display("COUNT reads=%0d",received);
        $display("COUNT full_waits=%0d",check_fifo.full_waits);$display("COUNT empty_waits=%0d",check_fifo.empty_waits);
        $display("COUNT simultaneous=%0d",check_fifo.simultaneous);
        $display("COUNT full_releases=%0d",check_fifo.full_releases);$display("COUNT empty_releases=%0d",check_fifo.empty_releases);
        $display("RESULT PASS checks=%0d",received);$finish;
    end
    initial begin #1000000;$fatal(1,"FIFO watchdog expired");end
endmodule
