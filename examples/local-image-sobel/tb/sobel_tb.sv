`timescale 1ns/1ps
module sobel_tb;
    parameter W=5, H=4, MUTATION=0;
    localparam N=W*H;
    reg clk=0, rst_n=0, in_valid=0, out_ready=0;
    reg [7:0] in_pixel=0;
    wire in_ready, out_valid, out_last;
    wire [7:0] out_pixel;
    sobel_stream #(.W(W),.H(H),.MUTATION(MUTATION)) dut(.*);
    always #5 clk=~clk;
    reg [7:0] input_pixels[0:8191], expected_pixels[0:8191];
    reg [31:0] rng;
    reg [8:0] held_payload;
    reg held=0, source_held=0, reset_done=0;
    integer frames, seed, scenario, sent=0, pixels=0, completed=0, cycles=0, stall=0, r, c;
    string input_path, expected_path, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label); $fatal(1,"sent=%0d pixels=%0d cycle=%0d",sent,pixels,cycles); end
    endtask
    initial begin
        if (!$value$plusargs("INPUT=%s",input_path) || !$value$plusargs("EXPECTED=%s",expected_path) ||
            !$value$plusargs("WAVE=%s",wave) || !$value$plusargs("FRAMES=%d",frames) ||
            !$value$plusargs("SEED=%d",seed) || !$value$plusargs("SCENARIO=%d",scenario)) $fatal(1,"arguments required");
        if(frames*N>8192) $fatal(1,"too many pixels");
        $readmemh(input_path,input_pixels,0,frames*N-1); $readmemh(expected_path,expected_pixels,0,frames*N-1);
        $dumpfile(wave); $dumpvars(0,sobel_tb);
        rng=32'(seed)|1;
        repeat(3) @(negedge clk);
        rst_n=1;
        while(pixels<frames*N) begin
            rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
            if(!source_held) begin
                in_valid=sent<frames*N && (rng[2:0]!=0);
                if(sent<frames*N) in_pixel=input_pixels[sent];
            end
            if(out_valid && stall<3) begin out_ready=0;stall=stall+1;end
            else out_ready=rng[4:3]!=0;
            #1;
            if((^{in_ready,out_valid})===1'bx) fail("IMAGE_CONTROL");
            if(held && (!out_valid || {out_last,out_pixel}!==held_payload)) fail("IMAGE_HOLD");
            if(out_valid) begin
                if(out_last !== (pixels%N==N-1)) fail("IMAGE_LAST");
                if(out_pixel !== expected_pixels[pixels]) fail("IMAGE_DATA");
            end
            if(dut.window_valid && dut.window_ready && dut.magnitude==254) $display("COVER value/below-saturation");
            if(dut.window_valid && dut.window_ready && dut.magnitude==256) $display("COVER value/saturation-boundary");
            if(in_valid && !in_ready) $display("COVER input/backpressure");
            if(!in_valid && sent>0 && sent<frames*N) $display("COVER input/gap");
            if(out_valid && !out_ready) $display("COVER output/hold");
            held=out_valid && !out_ready; held_payload={out_last,out_pixel};
            source_held=in_valid && !in_ready;
            if(in_valid && in_ready) begin
                if(sent!=0 && sent%N==0) $display("COVER frame/continuous");
                sent=sent+1;
            end
            if(out_valid && out_ready) begin
                r=(pixels%N)/W; c=pixels%W;
                if((r==0 || r==H-1) && (c==0 || c==W-1)) $display("COVER pixel/corner");
                else if(r==0 || r==H-1 || c==0 || c==W-1) $display("COVER pixel/edge");
                else $display("COVER pixel/interior");
                if(out_pixel==0) $display("COVER value/zero");
                else if(out_pixel==255) $display("COVER value/saturated");
                else $display("COVER value/linear");
                if(out_last) begin completed=completed+1; $display("COVER frame/last");end
                pixels=pixels+1;
            end
            @(posedge clk); #1; @(negedge clk);
            if(scenario==1 && !reset_done && sent>=W+2) begin
                rst_n=0; in_valid=0; out_ready=0;
                repeat(3) @(negedge clk);
                sent=0; pixels=0; completed=0; held=0; source_held=0; stall=0; reset_done=1; rst_n=1;
                $display("COVER reset/mid-frame");
            end
            cycles=cycles+1;
            if(cycles>frames*N*100+1000) fail("IMAGE_COMPLETION");
        end
        in_valid=0;out_ready=1;
        repeat(8) begin
            #1;if(out_valid)fail("IMAGE_COMPLETION");
            @(posedge clk);#1;@(negedge clk);
        end
        if(sent!=frames*N || completed!=frames || (scenario==1 && !reset_done)) fail("IMAGE_COMPLETION");
        $display("COUNT pixels=%0d",pixels);$display("COUNT frames=%0d",completed);
        $display("COUNT accepted=%0d",sent);$display("COUNT resets=%0d",reset_done);
        $display("RESULT PASS checks=%0d",pixels);$finish;
    end
endmodule
