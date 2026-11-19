`timescale 1ns/1ps
module video_double_buffer_tb;
    parameter integer WIDTH=8,HEIGHT=4,WR_PERIOD=7,PIX_PERIOD=20,PIX_PHASE=3,MUTATION=0;
    localparam integer N=WIDTH*HEIGHT, FRAME_CYCLES=(WIDTH+4)*(HEIGHT+3), INPUTS=4*N;
    reg wr_clk=0,pix_clk=0,arst_n=0;
    initial forever #(WR_PERIOD/2.0)wr_clk=~wr_clk;
    initial begin #(PIX_PHASE);forever #(PIX_PERIOD/2.0)pix_clk=~pix_clk;end
    reg in_valid=0,in_sof=0,in_eol=0;
    reg [23:0] in_rgb=0;
    reg [15:0] in_frame=0;
    wire in_ready,de,hsync,vsync,frame_valid,protocol_error;
    wire [23:0] rgb;
    wire [15:0] frame_id;
    video_double_buffer #(.WIDTH(WIDTH),.HEIGHT(HEIGHT),.MUTATION(MUTATION)) dut(.*);
    reg [23:0] pixels[0:INPUTS-1];
    reg sofs[0:INPUTS-1],eols[0:INPUTS-1];
    reg [15:0] frames[0:INPUTS-1];
    integer expected_checks,seed,generation=0,written=0,cycles=0,fd,accepted_fd,vfd,n;
    integer gap=0,last_gap_frame=0,stalls=0,published=0,repeats=0,swaps=0;
    reg taken=0,stalled=0,was_running;
    reg [41:0] held;
    reg [31:0] rng;
    reg [15:0] previous_frame=0;
    string vectors,wave,csv,test_name;

    function automatic [31:0] advance(input [31:0] value);
        reg [31:0] x;
        begin x=value^(value<<13);x=x^(x>>17);advance=x^(x<<5);end
    endfunction
    task fail(input string reason);
        $display("CHECK_FAIL VIDEO_DOUBLE_BUFFER");
        $fatal(1,"case=%s seed=%0d generation=%0d cycle=%0d frame=%0d clocks=%0d/%0d phase=%0d size=%0dx%0d written=%0d reason=%s",
            test_name,seed,generation,cycles,frame_id,WR_PERIOD,PIX_PERIOD,PIX_PHASE,WIDTH,HEIGHT,written,reason);
    endtask

    always @(negedge wr_clk)begin
        if(!arst_n)begin in_valid<=0;gap=0;last_gap_frame=0;end
        else if(!(in_valid && !taken))begin
            rng=advance(rng);
            if(generation==1 && written>0 && written%N==0 && last_gap_frame!=written/N)begin
                last_gap_frame=written/N;
                // A bounded producer pause forces full-frame repetition.
                gap=written/N==2 ? (FRAME_CYCLES*PIX_PERIOD*2/WR_PERIOD+7):3;
            end
            if(gap>0)begin gap=gap-1;in_valid<=0;end
            else begin
                in_valid<=written<(generation==0 ? (N>1 ? N/2:1):INPUTS) && rng[2:0]!=0;
                if(written<INPUTS)begin
                    in_rgb<=generation==0 ? 24'hbadbad:pixels[written];
                    in_frame<=generation==0 ? 16'd1:frames[written];
                    in_sof<=sofs[written];in_eol<=eols[written];
                end
            end
        end
    end
    always @(posedge wr_clk or negedge arst_n)begin
        if(!arst_n)begin written<=0;taken<=0;stalled<=0;end
        else begin
            if(stalled && (in_valid !== 1 || {in_rgb,in_sof,in_eol,in_frame} !== held[41:0]))
                fail("input packet changed while stalled");
            taken<=in_valid && in_ready;
            stalled<=in_valid && !in_ready;held<={in_rgb,in_sof,in_eol,in_frame};
            if(in_valid && !in_ready)stalls=stalls+1;
            if(in_valid && in_ready)begin
                if(dut.show_valid && dut.write_bank==dut.show_bank)fail("producer overwrote the displayed bank");
                $fdisplay(accepted_fd,"%0d,%0d,%h,%b,%b,%0d",generation,written,in_rgb,in_sof,in_eol,in_frame);
                written<=written+1;
                if((written+1)%N==0)published=published+1;
            end
            #0.001;
            if(protocol_error !== 0)fail("packet protocol error");
        end
    end
    always @(posedge pix_clk or negedge arst_n)begin
        if(!arst_n)begin cycles=0;previous_frame=0;end
        else begin
            was_running=dut.pixel_running;
            #0.001;
            if(was_running && generation==1)begin
                $fdisplay(fd,"%0d,%0d,%h,%b,%b,%b,%b",cycles,frame_id,rgb,de,hsync,vsync,frame_valid);
                if(cycles%FRAME_CYCLES==0 && frame_valid)begin
                    if(frame_id==previous_frame)repeats=repeats+1;else swaps=swaps+1;
                    previous_frame=frame_id;
                end
                cycles=cycles+1;
            end
        end
    end
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("CHECKS=%d",expected_checks)||
            !$value$plusargs("SEED=%d",seed)||!$value$plusargs("CSV=%s",csv)||
            !$value$plusargs("CASE=%s",test_name))$fatal(1,"arguments required");
        if($value$plusargs("WAVE=%s",wave))begin $dumpfile(wave);$dumpvars(0,video_double_buffer_tb);end
        rng=32'(seed)^32'h3311;
        fd=$fopen(csv,"w");$fdisplay(fd,"cycle,frame,rgb,de,hsync,vsync,valid");
        accepted_fd=$fopen({csv,".accepted"},"w");$fdisplay(accepted_fd,"generation,index,rgb,sof,eol,frame");
        vfd=$fopen(vectors,"r");if(!vfd)$fatal(1,"vectors missing");
        for(integer i=0;i<INPUTS;i=i+1)begin
            n=$fscanf(vfd,"%h %h %h %h\n",pixels[i],sofs[i],eols[i],frames[i]);
            if(n!=4)$fatal(1,"bad frame vector");
        end
        $fclose(vfd);
        repeat(7)@(negedge wr_clk);arst_n=1;
        wait(written==(N>1 ? N/2:1));#1;
        $display("COVER reset/pending");arst_n=0;generation=1;
        repeat(7)@(negedge wr_clk);arst_n=1;
        wait(cycles==expected_checks);
        @(negedge pix_clk);
        if(written!=INPUTS || !published || !stalls)fail("input completion or backpressure missing");
        $display("COVER input/backpressure");$display("COVER frame/published");
        if(swaps>=4)$display("COVER frame/boundary-swap");
        if(repeats>0)$display("COVER frame/repeated");
        $display("COVER reset/new-generation");
        $fclose(fd);$fclose(accepted_fd);
        $display("COUNT steps=%0d",cycles);$display("RESULT PASS checks=%0d",cycles);$finish;
    end
    initial begin #10000000;fail("timeout");end
endmodule
