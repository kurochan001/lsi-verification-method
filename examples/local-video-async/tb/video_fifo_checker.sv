`timescale 1ns/1ps
// Each side owns one sequence index. NBA queue writes remove same-time TB races.
// A readable entry was written before its pointer traversed the synchronizer.
module video_fifo_checker #(parameter DATA_W=58,DEPTH=16,ID=0,MAX_WORDS=65536)(
    input wire wclk,rclk,arst_n,wr_reset_n,rd_reset_n,
    input wire wr_valid,wr_ready,input wire [DATA_W-1:0] wr_data,
    input wire rd_valid,rd_ready,input wire [DATA_W-1:0] rd_data,
    input wire [$clog2(DEPTH):0] wbin,rbin,wgray,rgray
);
    localparam A=$clog2(DEPTH);
    reg [DATA_W-1:0] queue[0:MAX_WORDS-1];
    integer written=0,read_count=0,full_waits=0,empty_waits=0,simultaneous=0;
    integer full_releases=0,empty_releases=0;
    reg previous_ready=1,previous_valid=0;
    reg wstalled=0,rstalled=0;
    reg [DATA_W-1:0] held_w,held_r;
    reg [A:0] old_wgray,old_rgray,old_wbin,old_rbin,delta_w,delta_r;
    reg push,pop;
    time last_write=0;
    task fail(input string label);
        begin
            $display("CHECK_FAIL FIFO_%0d_%s written=%0d read=%0d expected=%h actual=%h time=%0t",
                     ID,label,written,read_count,queue[read_count],rd_data,$time);
            $fatal(1,"FIFO protocol or ordering failure");
        end
    endtask
    always @(posedge wclk or negedge arst_n) begin
        if (!arst_n) begin written<=0;full_waits<=0;wstalled<=0;last_write<=0;full_releases<=0;previous_ready<=1;end
        else if (wr_reset_n) begin
            if ((^{wr_valid,wr_ready})===1'bx) fail("WRITE_UNKNOWN");
            if (wstalled && (wr_valid!==1'b1 || wr_data!==held_w)) fail("WRITE_HOLD");
            if (wr_valid && wr_ready) begin
                if ((^wr_data)===1'bx || written>=MAX_WORDS) fail("WRITE_DATA");
                queue[written]<=wr_data; written<=written+1; last_write<=$time;
            end
            if (wr_valid && !wr_ready) full_waits<=full_waits+1;
            if (!previous_ready && wr_ready) full_releases<=full_releases+1;
            previous_ready<=wr_ready;
            held_w<=wr_data; wstalled<=wr_valid && !wr_ready;
            old_wgray=wgray;old_wbin=wbin;push=wr_valid && wr_ready;
            #1;
            if (arst_n) begin
                delta_w=wgray^old_wgray;
                if ((^delta_w)===1'bx || (delta_w & (delta_w-1'b1))!=0 ||
                    wbin!==old_wbin+{{A{1'b0}},push} || wgray!==((wbin>>1)^wbin) ||
                    (push ? delta_w==0:delta_w!=0)) fail("LOCAL_WRITE_GRAY");
            end
        end
    end
    always @(posedge rclk or negedge arst_n) begin
        if (!arst_n) begin read_count<=0;empty_waits<=0;rstalled<=0;simultaneous<=0;empty_releases<=0;previous_valid<=0;end
        else if (rd_reset_n) begin
            if ((^{rd_valid,rd_ready})===1'bx) fail("READ_UNKNOWN");
            if (rstalled && (rd_valid!==1'b1 || rd_data!==held_r)) fail("READ_HOLD");
            if (rd_valid && rd_ready) begin
                if (read_count>=written || rd_data!==queue[read_count]) fail("ORDER");
                read_count<=read_count+1;
            end
            if (rd_ready && !rd_valid) empty_waits<=empty_waits+1;
            if (!previous_valid && rd_valid) empty_releases<=empty_releases+1;
            previous_valid<=rd_valid;
            held_r<=rd_data;rstalled<=rd_valid && !rd_ready;
            old_rgray=rgray;old_rbin=rbin;pop=rd_valid && rd_ready;
            #1;
            if (arst_n) begin
                delta_r=rgray^old_rgray;
                if ((^delta_r)===1'bx || (delta_r & (delta_r-1'b1))!=0 ||
                    rbin!==old_rbin+{{A{1'b0}},pop} || rgray!==((rbin>>1)^rbin) ||
                    (pop ? delta_r==0:delta_r!=0)) fail("LOCAL_READ_GRAY");
                if (pop && last_write==$time-1) simultaneous<=simultaneous+1;
            end
        end
    end
endmodule
