// Independent domains, atomic pixel packets, and a coordinated reset barrier.
module video_async_pipeline #(
    parameter W=64,H=32,D0=16,D1=16,D2=128,PREFILL=64,DISPLAY=1,
    parameter H_FP=8,H_SYNC=4,H_BP=4,V_FP=3,V_SYNC=2,V_BP=3,
    parameter [23:0] KEY=24'h51905a
)(
    input wire clk_key,clk_csc,clk_blend,clk_pix,arst_n,
    input wire in_valid,output wire in_ready,input wire [57:0] in_data,
    output wire out_valid,input wire out_ready,output wire [25:0] out_data,
    output wire [23:0] rgb,output wire de,hsync,vsync,
    output wire started,video_error,underflow,marker_error,
    output wire [$clog2(W+H_FP+H_SYNC+H_BP)-1:0] out_x,
    output wire [$clog2(H+V_FP+V_SYNC+V_BP)-1:0] out_y,
    output wire [$clog2(D2):0] display_level,
    output wire [$clog2(D0):0] fifo0_level,
    output wire [$clog2(D1):0] fifo1_level
);
    wire key_reset_n,csc_reset_n,blend_reset_n,pix_reset_n;
    wire key_run,csc_run,blend_run,pix_run;
    video_reset_sync rk(clk_key,arst_n,key_reset_n);
    video_reset_sync rc(clk_csc,arst_n,csc_reset_n);
    video_reset_sync rb(clk_blend,arst_n,blend_reset_n);
    video_reset_sync rp(clk_pix,arst_n,pix_reset_n);
    // All FIFO endpoints leave local reset before any domain may accept traffic.
    wire all_released=key_reset_n && csc_reset_n && blend_reset_n && pix_reset_n;
    video_reset_sync gk(clk_key,arst_n && all_released,key_run);
    video_reset_sync gc(clk_csc,arst_n && all_released,csc_run);
    video_reset_sync gb(clk_blend,arst_n && all_released,blend_run);
    video_reset_sync gp(clk_pix,arst_n && all_released,pix_run);
    wire k_valid,k_ready,c_valid,c_ready,b_valid,b_ready;
    wire f0_valid,f0_ready,f1_valid,f1_ready,f2_valid,f2_ready;
    wire key_input_ready;
    wire [57:0] k_data,c_data,f0_data,f1_data;
    wire [25:0] b_data,f2_data;
    // Display mode owns the sink; this terminates its unused stream-only input.
    wire unused_stream_ready=out_ready;
    assign in_ready=key_run && key_input_ready;
    video_key #(.KEY(KEY)) key_stage(clk_key,key_reset_n,key_run,in_valid && key_run,key_input_ready,in_data,k_valid,k_ready,k_data);
    video_async_fifo #(.DATA_W(58),.DEPTH(D0)) fifo0(clk_key,clk_csc,key_reset_n,csc_reset_n,k_valid,k_ready,k_data,f0_valid,f0_ready,f0_data,fifo0_level);
    video_csc csc_stage(clk_csc,csc_reset_n,csc_run,f0_valid,f0_ready,f0_data,c_valid,c_ready,c_data);
    video_async_fifo #(.DATA_W(58),.DEPTH(D1)) fifo1(clk_csc,clk_blend,csc_reset_n,blend_reset_n,c_valid,c_ready,c_data,f1_valid,f1_ready,f1_data,fifo1_level);
    video_blend blend_stage(clk_blend,blend_reset_n,blend_run,f1_valid,f1_ready,f1_data,b_valid,b_ready,b_data);
    video_async_fifo #(.DATA_W(26),.DEPTH(D2)) fifo2(clk_blend,clk_pix,blend_reset_n,pix_reset_n,b_valid,b_ready,b_data,f2_valid,f2_ready,f2_data,display_level);
    assign out_valid=pix_run && f2_valid;
    assign out_data=f2_data;
    generate if (DISPLAY!=0) begin: display_mode
        video_display #(.W(W),.H(H),.DEPTH(D2),.PREFILL(PREFILL),
            .H_FP(H_FP),.H_SYNC(H_SYNC),.H_BP(H_BP),.V_FP(V_FP),.V_SYNC(V_SYNC),.V_BP(V_BP))
            display(clk_pix,pix_reset_n,pix_run,f2_valid,f2_ready,f2_data,display_level,
                    rgb,de,hsync,vsync,started,video_error,underflow,marker_error,out_x,out_y);
    end else begin: stream_mode
        assign f2_ready=pix_run && out_ready;
        assign rgb=0; assign de=0; assign hsync=1; assign vsync=1;
        assign started=0; assign video_error=0; assign underflow=0; assign marker_error=0;
        assign out_x=0; assign out_y=0;
    end endgenerate
endmodule
