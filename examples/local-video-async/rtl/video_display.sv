// Fixed pixel timing. An error latches black output until coordinated reset.
module video_display #(
    parameter W=64,H=32,H_FP=8,H_SYNC=4,H_BP=4,V_FP=3,V_SYNC=2,V_BP=3,
    parameter DEPTH=128,PREFILL=64
)(
    input wire clk,reset_n,active,s_valid,output wire s_ready,input wire [25:0] s_data,
    input wire [$clog2(DEPTH):0] read_level,
    output reg [23:0] rgb,output reg de,hsync,vsync,
    output reg started,video_error,underflow,marker_error,
    output reg [$clog2(W+H_FP+H_SYNC+H_BP)-1:0] out_x,
    output reg [$clog2(H+V_FP+V_SYNC+V_BP)-1:0] out_y
);
    localparam HT=W+H_FP+H_SYNC+H_BP,VT=H+V_FP+V_SYNC+V_BP;
    localparam XW=$clog2(HT),YW=$clog2(VT);
    localparam FILL=(PREFILL<DEPTH ? PREFILL:DEPTH)<W*H ? (PREFILL<DEPTH ? PREFILL:DEPTH):W*H;
    reg [XW-1:0] x;
    reg [YW-1:0] y;
    wire visible=int'(x)<W && int'(y)<H;
    wire correct_markers=s_data[25]==(x==0 && y==0) && s_data[24]==(int'(x)==W-1);
    assign s_ready=active && started && visible && !video_error;
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            x<=0; y<=0; out_x<=0; out_y<=0; rgb<=0; de<=0; hsync<=1; vsync<=1;
            started<=0; video_error<=0; underflow<=0; marker_error<=0;
        end else if (active) begin
            rgb<=0;
            if (!started) begin
                if (s_valid && s_data[25] && int'(read_level)>=FILL) started<=1;
            end else begin
                out_x<=x; out_y<=y; de<=visible;
                hsync<=!(int'(x)>=W+H_FP && int'(x)<W+H_FP+H_SYNC);
                vsync<=!(int'(y)>=H+V_FP && int'(y)<H+V_FP+V_SYNC);
                if (visible && !video_error) begin
                    if (!s_valid) begin video_error<=1; underflow<=1; end
                    else if (!correct_markers) begin video_error<=1; marker_error<=1; end
                    else rgb<=s_data[23:0];
                end
                if (int'(x)==HT-1) begin
                    x<=0;
                    if (int'(y)==VT-1) y<=0;
                    else y<=y+1'b1;
                end else x<=x+1'b1;
            end
        end
    end
endmodule
