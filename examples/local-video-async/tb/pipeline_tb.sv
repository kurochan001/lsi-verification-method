`timescale 1ns/1ps
module pipeline_tb;
    parameter W=64,H=32,FRAMES=3,D0=16,D1=16,D2=128,PREFILL=64,DISPLAY=1;
    parameter BUBBLES=0,STALLS=0,RESET_TEST=0,UNDERFLOW_KIND=0,CHANGE_OK=0;
    parameter H_FP=8,H_SYNC=4,H_BP=4,V_FP=3,V_SYNC=2,V_BP=3;
    localparam TOTAL=W*H*FRAMES,HT=W+H_FP+H_SYNC+H_BP,VT=H+V_FP+V_SYNC+V_BP;
    localparam FILL=(PREFILL<D2 ? PREFILL:D2)<W*H ? (PREFILL<D2 ? PREFILL:D2):W*H;
    reg clk_key=0,clk_csc=0,clk_blend=0,clk_pix=0,arst_n=1;
    reg in_valid=0,out_ready=0;
    reg [57:0] in_data=0;
    wire in_ready,out_valid;
    wire [25:0] out_data;
    wire [23:0] rgb;
    wire de,hsync,vsync,started,video_error,underflow,marker_error;
    wire [$clog2(HT)-1:0] out_x;
    wire [$clog2(VT)-1:0] out_y;
    wire [$clog2(D2):0] display_level;
    wire [$clog2(D0):0] fifo0_level;
    wire [$clog2(D1):0] fifo1_level;
    video_async_pipeline #(.W(W),.H(H),.D0(D0),.D1(D1),.D2(D2),.PREFILL(PREFILL),.DISPLAY(DISPLAY),
        .H_FP(H_FP),.H_SYNC(H_SYNC),.H_BP(H_BP),.V_FP(V_FP),.V_SYNC(V_SYNC),.V_BP(V_BP)) dut(.*);
    video_fifo_checker #(.DATA_W(58),.DEPTH(D0),.ID(0)) ck0(
        clk_key,clk_csc,arst_n,dut.key_reset_n,dut.csc_reset_n,dut.k_valid,dut.k_ready,dut.k_data,
        dut.f0_valid,dut.f0_ready,dut.f0_data,dut.fifo0.wbin,dut.fifo0.rbin,dut.fifo0.wgray,dut.fifo0.rgray);
    video_fifo_checker #(.DATA_W(58),.DEPTH(D1),.ID(1)) ck1(
        clk_csc,clk_blend,arst_n,dut.csc_reset_n,dut.blend_reset_n,dut.c_valid,dut.c_ready,dut.c_data,
        dut.f1_valid,dut.f1_ready,dut.f1_data,dut.fifo1.wbin,dut.fifo1.rbin,dut.fifo1.wgray,dut.fifo1.rgray);
    video_fifo_checker #(.DATA_W(26),.DEPTH(D2),.ID(2)) ck2(
        clk_blend,clk_pix,arst_n,dut.blend_reset_n,dut.pix_reset_n,dut.b_valid,dut.b_ready,dut.b_data,
        dut.f2_valid,dut.f2_ready,dut.f2_data,dut.fifo2.wbin,dut.fifo2.rbin,dut.fifo2.wgray,dut.fifo2.rgray);

    reg [57:0] raw[0:2*TOTAL-1],key_expected[0:2*TOTAL-1],csc_expected[0:2*TOTAL-1];
    reg [25:0] blend_expected[0:2*TOTAL-1];
    reg configured=0,input_taken=0,pause_source=0,reset_done=0,clock_changed=0,saw_underflow=0;
    reg source_stalled=0;
    reg [57:0] held_source;
    integer sent=0,key_received=0,csc_received=0,received=0,epoch=0;
    integer pix_cycles=0,display_frames=0,mx=0,my=0,displayed=0,error_pixels=0;
    integer input_waits=0,max_level=0,checks=0,epoch0_discard=0;
    reg [31:0] seed=17,source_rng=1,sink_rng=2;
    integer bubble_run=0,stall_run=0;
    real key_ns=10.0,csc_ns=13.0,blend_ns=17.0,pix_ns=20.0;
    real key_phase=0.0,csc_phase=1.0,blend_phase=3.0,pix_phase=7.0;
    real kh,ch,bh,ph,base_csc;
    integer pixels_fd,levels_fd;
    string directory,test_name="pipeline",wave;

    function automatic [31:0] next_rng(input [31:0] state);
        reg [31:0] value;
        begin value=state^(state<<13);value=value^(value>>17);next_rng=value^(value<<5);end
    endfunction
    task automatic fail(input string label,input [57:0] expected,actual);
        integer index_value,failed_frame,failed_x,failed_y;
        begin
            index_value=-1;failed_frame=display_frames;failed_x=mx;failed_y=my;
            if (label=="KEY_PACKET") index_value=key_received;
            else if (label=="CSC_PACKET") index_value=csc_received;
            else if (label=="BLEND_PACKET" || !DISPLAY) index_value=received;
            if (label=="INPUT_ORDER" || label=="INPUT_HOLD" || label=="INPUT_UNKNOWN") index_value=sent;
            if (index_value>=0) begin
                failed_frame=index_value/(W*H);failed_x=index_value%W;failed_y=(index_value/W)%H;
            end
            $display("CHECK_FAIL %s test=%s seed=%0d epoch=%0d frame=%0d x=%0d y=%0d expected=%h actual=%h",
                     label,test_name,seed,epoch,failed_frame,failed_x,failed_y,expected,actual);
            $display("clocks_ns=%0.3f,%0.3f,%0.3f,%0.3f phases_ns=%0.3f,%0.3f,%0.3f,%0.3f depths=%0d,%0d,%0d sent=%0d received=%0d time=%0t",
                     key_ns,csc_ns,blend_ns,pix_ns,key_phase,csc_phase,blend_phase,pix_phase,D0,D1,D2,sent,received,$time);
            $fatal(1,"pipeline mismatch");
        end
    endtask

    initial begin
        if (!$value$plusargs("DIR=%s",directory)) $fatal(1,"DIR required");
        if ($value$plusargs("CASE=%s",test_name)) begin end
        if ($value$plusargs("SEED=%d",seed)) begin end
        if ($value$plusargs("KEY_NS=%f",key_ns)) begin end
        if ($value$plusargs("CSC_NS=%f",csc_ns)) begin end
        if ($value$plusargs("BLEND_NS=%f",blend_ns)) begin end
        if ($value$plusargs("PIX_NS=%f",pix_ns)) begin end
        if ($value$plusargs("KEY_PHASE=%f",key_phase)) begin end
        if ($value$plusargs("CSC_PHASE=%f",csc_phase)) begin end
        if ($value$plusargs("BLEND_PHASE=%f",blend_phase)) begin end
        if ($value$plusargs("PIX_PHASE=%f",pix_phase)) begin end
        if ($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,pipeline_tb);end
        $readmemh({directory,"/input.hex"},raw);$readmemh({directory,"/key.hex"},key_expected);
        $readmemh({directory,"/csc.hex"},csc_expected);$readmemh({directory,"/blend.hex"},blend_expected);
        pixels_fd=$fopen({directory,"/pixels.csv"},"w");levels_fd=$fopen({directory,"/occupancy.csv"},"w");
        if (!pixels_fd || !levels_fd) $fatal(1,"cannot create output evidence");
        $fdisplay(pixels_fd,"epoch,frame,x,y,rgb,error");
        $fdisplay(levels_fd,"time_ns,epoch,started,x,y,de,read_level,accepted_balance,error,csc_ns");
        source_rng=seed==0 ? 32'h6d2b79f5:seed;sink_rng=source_rng^32'ha5a55a5a;base_csc=csc_ns;
        $display("CONFIG test=%s seed=%0d size=%0dx%0d clocks=%0.3f,%0.3f,%0.3f,%0.3f depths=%0d,%0d,%0d",
                 test_name,seed,W,H,key_ns,csc_ns,blend_ns,pix_ns,D0,D1,D2);
        configured=1;#1;arst_n=0;#120;arst_n=1;
    end
    // Capture a period for a complete low/high pair; changes never truncate pulses.
    initial begin wait(configured);#(key_phase);forever begin kh=key_ns/2.0;#(kh)clk_key=1;#(kh)clk_key=0;end end
    initial begin wait(configured);#(csc_phase);forever begin ch=csc_ns/2.0;#(ch)clk_csc=1;#(ch)clk_csc=0;end end
    initial begin wait(configured);#(blend_phase);forever begin bh=blend_ns/2.0;#(bh)clk_blend=1;#(bh)clk_blend=0;end end
    initial begin wait(configured);#(pix_phase);forever begin ph=pix_ns/2.0;#(ph)clk_pix=1;#(ph)clk_pix=0;end end

    always @(posedge clk_key or negedge arst_n) begin
        if (!arst_n) begin sent<=0;input_taken<=0;source_stalled<=0;input_waits<=0;end
        else begin
            if ((^{in_valid,in_ready})===1'bx) fail("INPUT_UNKNOWN",0,in_data);
            if (in_ready && !dut.key_run) fail("RESET_BARRIER",0,1);
            if (source_stalled && (in_valid!==1'b1 || in_data!==held_source)) fail("INPUT_HOLD",held_source,in_data);
            input_taken<=in_valid && in_ready;
            if (in_valid && in_ready) begin
                if (sent>=TOTAL || in_data!==raw[epoch*TOTAL+sent]) fail("INPUT_ORDER",raw[epoch*TOTAL+sent],in_data);
                sent<=sent+1;
            end
            if (in_valid && !in_ready) input_waits<=input_waits+1;
            source_stalled<=in_valid && !in_ready;held_source<=in_data;
        end
    end
    always @(negedge clk_key) begin
        if (!arst_n || !dut.key_run) begin in_valid<=0;in_data<=0;bubble_run<=0;end
        else if (!in_valid || input_taken) begin
            source_rng<=next_rng(source_rng);
            if (sent>=TOTAL || pause_source || (BUBBLES!=0 && source_rng%6==0 && bubble_run<2)) begin
                in_valid<=0;bubble_run<=bubble_run+1;
            end else begin in_valid<=1;in_data<=raw[epoch*TOTAL+sent];bubble_run<=0;end
        end
    end
    always @(negedge clk_pix) begin
        sink_rng<=next_rng(sink_rng);
        if (!arst_n || !dut.pix_run) begin out_ready<=0;stall_run<=0;end
        else if (STALLS!=0 && (pix_cycles<1000 || (sink_rng%4==0 && stall_run<3))) begin out_ready<=0;stall_run<=stall_run+1;end
        else begin out_ready<=1;stall_run<=0;end
    end
    always @(posedge clk_csc or negedge arst_n) begin
        if (!arst_n) key_received<=0;
        else if (dut.f0_valid && dut.f0_ready) begin
            if (key_received>=TOTAL || dut.f0_data!==key_expected[epoch*TOTAL+key_received]) fail("KEY_PACKET",key_expected[epoch*TOTAL+key_received],dut.f0_data);
            key_received<=key_received+1;
        end
    end
    always @(posedge clk_blend or negedge arst_n) begin
        if (!arst_n) csc_received<=0;
        else if (dut.f1_valid && dut.f1_ready) begin
            if (csc_received>=TOTAL || dut.f1_data!==csc_expected[epoch*TOTAL+csc_received]) fail("CSC_PACKET",csc_expected[epoch*TOTAL+csc_received],dut.f1_data);
            csc_received<=csc_received+1;
        end
    end

    reg pre_started,pre_valid,pre_ready,pre_error;
    reg [25:0] pre_data;
    integer pre_level,pre_balance;
    always @(posedge clk_pix or negedge arst_n) begin
        if (!arst_n) begin
            received=0;pix_cycles=0;display_frames=0;mx=0;my=0;displayed=0;error_pixels=0;max_level=0;
        end else begin
            pre_started=started;pre_valid=dut.f2_valid;pre_ready=dut.f2_ready;pre_error=video_error;
            pre_data=dut.f2_data;pre_level=int'(display_level);pre_balance=ck2.written-ck2.read_count;
            if ((^{pre_valid,pre_ready})===1'bx) fail("SINK_UNKNOWN",0,0);
            if (pre_valid && pre_ready) begin
                if (received>=TOTAL || pre_data!==blend_expected[epoch*TOTAL+received]) fail("BLEND_PACKET",{32'd0,blend_expected[epoch*TOTAL+received]},{32'd0,pre_data});
                if (!DISPLAY) $fdisplay(pixels_fd,"%0d,%0d,%0d,%0d,%06h,0",epoch,received/(W*H),received%W,(received/W)%H,pre_data[23:0]);
                received=received+1;
            end
            #1;
            if (arst_n) begin
                pix_cycles=pix_cycles+1;checks=checks+1;
                if (pre_level>max_level) max_level=pre_level;
                if (marker_error!==1'b0) fail("DISPLAY_MARKER",0,1);
                if (DISPLAY && started && !pre_started && (!pre_valid || !pre_data[25] || pre_level<FILL)) fail("PREFILL",58'(FILL),58'(pre_level));
                if (UNDERFLOW_KIND==0 && video_error!==1'b0) fail("UNEXPECTED_UNDERFLOW",0,1);
                if (DISPLAY && pre_started) begin
                    if ({de,hsync,vsync}!=={(mx<W && my<H),!(mx>=W+H_FP && mx<W+H_FP+H_SYNC),!(my>=H+V_FP && my<H+V_FP+V_SYNC)} ||
                        (^{out_x,out_y})===1'bx || int'(out_x)!=mx || int'(out_y)!=my) fail("DISPLAY_TIMING",58'(mx),58'(out_x));
                    if (pre_ready && !(mx<W && my<H)) fail("BLANKING_CONSUMPTION",0,1);
                    if (de) begin
                        displayed=displayed+1;
                        if (video_error) begin
                            if (rgb!==24'd0 || pre_error && pre_ready) fail("ERROR_BLACK",0,{34'd0,rgb});
                            error_pixels=error_pixels+1;
                        end else begin
                            if (!pre_valid || !pre_ready || rgb!==pre_data[23:0]) fail("DISPLAY_RGB",{34'd0,pre_data[23:0]},{34'd0,rgb});
                        end
                        $fdisplay(pixels_fd,"%0d,%0d,%0d,%0d,%06h,%0d",epoch,display_frames,mx,my,rgb,video_error);
                    end else if (rgb!==24'd0) fail("BLANKING_RGB",0,{34'd0,rgb});
                    if (mx==HT-1) begin
                        mx=0;
                        if (my==VT-1) begin my=0;display_frames=display_frames+1;end
                        else my=my+1;
                    end else mx=mx+1;
                end else if (DISPLAY && (rgb!==0 || de!==0 || hsync!==1 || vsync!==1)) fail("STARTUP_BLACK",0,{34'd0,rgb});
                $fdisplay(levels_fd,"%0.3f,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0.3f",$realtime,epoch,started,out_x,out_y,de,pre_level,pre_balance,video_error,csc_ns);
                if ((DISPLAY ? display_frames==FRAMES : received==TOTAL) &&
                    (RESET_TEST==0 && UNDERFLOW_KIND==0 || reset_done)) begin
                    if (sent!=TOTAL || key_received!=TOTAL || csc_received!=TOTAL || received!=TOTAL) fail("COMPLETION_COUNTS",58'(TOTAL),58'(received));
                    if (STALLS && TOTAL>D0+D1+D2+3 && input_waits==0) fail("BACKPRESSURE_MISSING",1,0);
                    if (CHANGE_OK && !clock_changed) fail("CLOCK_CHANGE_MISSING",1,0);
                    if (UNDERFLOW_KIND!=0 && !saw_underflow) fail("UNDERFLOW_MISSING",1,0);
                    $display("COUNT accepted_in=%0d",sent);$display("COUNT accepted_out=%0d",received);
                    $display("COUNT full_waits=%0d",ck0.full_waits+ck1.full_waits+ck2.full_waits);
                    $display("COUNT max_level=%0d",max_level);$display("COUNT reset_epochs=%0d",epoch);
                    $display("COUNT discarded=%0d",epoch0_discard);
                    $display("RESULT PASS checks=%0d",checks);$fclose(pixels_fd);$fclose(levels_fd);$finish;
                end
            end
        end
    end

    task coordinated_reset;
        begin
            if (ck2.written<=ck2.read_count) fail("RESET_NOT_BUSY",1,0);
            #3.123;epoch0_discard=sent-received;
            $display("RESET_DISCARD epoch=%0d accepted=%0d output=%0d pending=%0d",epoch,sent,received,epoch0_discard);
            arst_n=0;epoch=1;pause_source=0;csc_ns=base_csc;
            #(pix_ns*9.3);reset_done=1;arst_n=1;
        end
    endtask
    initial begin
        wait(configured);wait(arst_n===1'b0);wait(arst_n===1'b1);
        if (UNDERFLOW_KIND!=0) begin
            wait(started && displayed>=W*H/4);
            if (UNDERFLOW_KIND==1) begin pause_source=1;$display("EXPECTED_ERROR source_pause begin time_ns=%0.3f",$realtime);end
            else begin csc_ns=pix_ns*4.0;$display("EXPECTED_ERROR clock_slowdown period_ns=%0.3f time_ns=%0.3f",csc_ns,$realtime);end
            wait(underflow===1'b1);saw_underflow=1;
            $display("EXPECTED_ERROR display_underflow observed time_ns=%0.3f",$realtime);
            pause_source=0;csc_ns=base_csc;
            // Late pixels return, but the display must remain black with running sync.
            #(pix_ns*HT*VT*1.1);
            if (!video_error || error_pixels<W*H || !started) fail("ERROR_NOT_LATCHED",1,0);
            coordinated_reset();
        end else if (RESET_TEST!=0) begin
            if (DISPLAY) wait(started && displayed>=W*H/3);
            else wait(received>=W*H/3);
            coordinated_reset();
        end else if (CHANGE_OK!=0) begin
            wait(started && displayed>=W*H/4);csc_ns=pix_ns*1.1;clock_changed=1;
            $display("CLOCK_CHANGE safe_slow period_ns=%0.3f time_ns=%0.3f",csc_ns,$realtime);
            #(pix_ns*HT*H/2.0);csc_ns=base_csc;
            $display("CLOCK_CHANGE restored period_ns=%0.3f time_ns=%0.3f",csc_ns,$realtime);
        end
    end
    real last_csc_fall=0,last_csc_rise=0,measured_low=0,measured_high;
    always @(posedge clk_csc) begin
        if (last_csc_fall!=0) measured_low=$realtime-last_csc_fall;
        last_csc_rise=$realtime;
    end
    always @(negedge clk_csc) begin
        measured_high=$realtime-last_csc_rise;
        if (measured_low!=0 && (measured_high<1.999 || measured_high-measured_low>0.002 || measured_low-measured_high>0.002))
            fail("CLOCK_PULSE_WIDTH",0,0);
        last_csc_fall=$realtime;
    end
    real slowest,latest;
    initial begin
        wait(configured);
        slowest=key_ns;
        if (csc_ns>slowest) slowest=csc_ns;
        if (blend_ns>slowest) slowest=blend_ns;
        if (pix_ns>slowest) slowest=pix_ns;
        latest=key_phase+csc_phase+blend_phase+pix_phase;
        #(latest+slowest*(TOTAL*32.0+HT*VT*FRAMES*16.0+10000.0));
        fail("WATCHDOG",58'(TOTAL),58'(received));
    end
endmodule
