`timescale 1ns/1ps
module async_fifo_tb;
    parameter DEPTH=4,SYNC_STAGES=2,MUTATION=0;
    localparam A=$clog2(DEPTH);
    reg wclk=0,rclk=0,rst_n=1,wr_en=0,rd_en=0;
    reg [7:0] wr_data=0;
    wire full,empty,rd_valid;wire [7:0] rd_data;
    async_fifo #(.DEPTH(DEPTH),.SYNC_STAGES(SYNC_STAGES),.MUTATION(MUTATION)) dut(.*);
    integer fd,rc,wc,rr,rst,we,value,re,profile,ef,ee,ev,ed;
    integer checks=0,writes=0,reads=0,blocked_writes=0,blocked_reads=0;
    integer epoch_w=0,epoch_r=0;
    reg wrise,rrise,pfull,pempty,preset=1,recovering=0,accepted_w,accepted_r;
    reg [A:0] old_wgray,old_rgray,delta_w,delta_r;
    string vectors,wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label);$fatal(1,"tick=%0d full=%b empty=%b valid=%b data=%h",checks,full,empty,rd_valid,rd_data);end
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"VECTORS required");
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,async_fifo_tb);end
        fd=$fopen(vectors,"r");if(!fd) $fatal(1,"cannot open vectors");
        while(!$feof(fd)) begin
            rc=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h\n",wc,rr,rst,we,value,re,profile,ef,ee,ev,ed);
            if(rc!=11) $fatal(1,"malformed vector");
            wrise=wc && !wclk;rrise=rr && !rclk;
            pfull=full;pempty=empty;old_wgray=dut.wgray;old_rgray=dut.rgray;
            accepted_w=rst && wrise && we && !full;
            accepted_r=rst && rrise && re && !empty;
            if(!rst && preset && (epoch_w!=epoch_r || !empty)) begin
                $display("COVER reset/active");recovering=1;
            end
            rst_n=rst;wr_en=we;wr_data=value;rd_en=re;
            #1;wclk=wc;rclk=rr;#1;
            if(rd_valid!==ev[0]) fail("ASYNC_VALID");
            if(rst) begin
                if((^dut.wgray)===1'bx || (^dut.rgray)===1'bx) fail("ASYNC_GRAY");
                delta_w=dut.wgray ^ old_wgray;delta_r=dut.rgray ^ old_rgray;
                if((delta_w & (delta_w-1))!=0 || (delta_r & (delta_r-1))!=0 ||
                    (accepted_w ? delta_w==0 : delta_w!=0) || (accepted_r ? delta_r==0 : delta_r!=0)) fail("ASYNC_GRAY");
            end
            if(full!==ef[0] || empty!==ee[0]) fail("ASYNC_FLAGS");
            if(rd_data!==ed[7:0]) fail("ASYNC_DATA");
            if(!rst) begin epoch_w=0;epoch_r=0;end
            else begin
                if(accepted_w) begin
                    writes=writes+1;epoch_w=epoch_w+1;$display("COVER transfer/write");
                end
                if(accepted_r) begin
                    reads=reads+1;epoch_r=epoch_r+1;$display("COVER transfer/read");
                    if(rd_data==0) $display("COVER data/zero");
                    if(rd_data==255) $display("COVER data/ones");
                    if(rd_data==85) $display("COVER data/alternating");
                    if(recovering) begin $display("COVER reset/recovery");recovering=0;end
                end
                if(wrise && we && pfull) begin blocked_writes=blocked_writes+1;$display("COVER boundary/full-block");end
                if(rrise && re && pempty) begin blocked_reads=blocked_reads+1;$display("COVER boundary/empty-block");end
                if(wrise && pfull && !full) $display("COVER flags/full-release");
                if(rrise && pempty && !empty) $display("COVER flags/empty-release");
                if(epoch_w>=2*DEPTH && epoch_r>=2*DEPTH) $display("COVER pointer/wrap");
                if(accepted_w && accepted_r) $display("COVER transfer/simultaneous");
                if(epoch_w>DEPTH && epoch_r>DEPTH) $display("COVER clock/profile%0d",profile);
            end
            preset=rst;checks=checks+1;
        end
        $fclose(fd);
        if(!empty) fail("ASYNC_DRAIN");
        $display("COUNT writes=%0d",writes);$display("COUNT reads=%0d",reads);
        $display("COUNT blocked_writes=%0d",blocked_writes);$display("COUNT blocked_reads=%0d",blocked_reads);
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
