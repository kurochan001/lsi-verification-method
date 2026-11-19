module video_double_buffer #(
    parameter integer WIDTH=8, HEIGHT=4,
    parameter integer H_FP=2,H_SYNC=1,H_BP=1,V_FP=1,V_SYNC=1,V_BP=1,
    parameter integer MUTATION=0
)(
    input wire wr_clk,pix_clk,arst_n,
    input wire in_valid,
    output wire in_ready,
    input wire [23:0] in_rgb,
    input wire in_sof,in_eol,
    input wire [15:0] in_frame,
    output reg [23:0] rgb,
    output reg de,hsync,vsync,frame_valid,
    output reg [15:0] frame_id,
    output reg protocol_error
);
    localparam integer PIXELS=WIDTH*HEIGHT, HT=WIDTH+H_FP+H_SYNC+H_BP, VT=HEIGHT+V_FP+V_SYNC+V_BP;
    localparam integer IW=PIXELS>1 ? $clog2(PIXELS):1, XW=$clog2(HT),YW=$clog2(VT);
    reg [23:0] memory[0:2*PIXELS-1];
    wire wr_up,pix_up;
    memory_reset_sync wr_release(.clk(wr_clk),.arst_n(arst_n),.up(wr_up));
    memory_reset_sync pix_release(.clk(pix_clk),.arst_n(arst_n),.up(pix_up));
    (* ASYNC_REG="TRUE" *) reg [1:0] ack_sync,request_sync,pix_alive,wr_alive;
    reg request_toggle,ack_toggle,write_bank,published_bank;
    reg [15:0] published_frame,input_frame;
    reg [IW-1:0] write_index;
    reg show_valid,show_bank;
    reg [15:0] show_frame;
    reg [XW-1:0] x;
    reg [YW-1:0] y;
    wire pixel_running=pix_up && wr_alive[1];
    wire pending=request_sync[1]!=ack_toggle;
    wire take_pending=pending && ((x==0 && y==0) || MUTATION==1);
    wire selected_valid=show_valid || take_pending;
    wire selected_bank=take_pending ? published_bank:show_bank;
    wire read_bank=(MUTATION==4 && take_pending) ? show_bank:selected_bank;
    wire [15:0] selected_frame=take_pending ? published_frame:show_frame;
    wire active=int'(x)<WIDTH && int'(y)<HEIGHT;
    wire accepted=in_valid && in_ready;
    wire packet_ok=(in_sof === (write_index==0)) &&
        (in_eol === (int'(write_index)%WIDTH==WIDTH-1)) &&
        (write_index==0 || (in_frame === input_frame));
    integer read_index;
    always @* begin
        read_index=int'(y)*WIDTH+int'(x);
        if(MUTATION==2)read_index=int'(y)*(WIDTH-1)+int'(x);
    end
    assign in_ready=wr_up && pix_alive[1] && !protocol_error &&
        ((request_toggle==ack_sync[1]) || MUTATION==3);

    always @(posedge wr_clk or negedge arst_n)begin
        if(!arst_n)begin
            request_toggle<=0;write_bank<=0;published_bank<=0;published_frame<=0;
            input_frame<=0;write_index<=0;ack_sync<=0;pix_alive<=0;protocol_error<=0;
        end else begin
            ack_sync<={ack_sync[0],ack_toggle};pix_alive<={pix_alive[0],pix_up};
            if(accepted)begin
                if(!packet_ok)protocol_error<=1;
                else begin
                    if(write_index==0)input_frame<=in_frame;
                    if(write_index==IW'(PIXELS-1))begin
                        published_bank<=write_bank;published_frame<=PIXELS==1 ? in_frame:input_frame;
                        request_toggle<=~request_toggle;write_bank<=~write_bank;write_index<=0;
                    end else write_index<=write_index+1'b1;
                end
            end
        end
    end
    // Synchronous write/read ports. Ownership prevents mixed-port collisions.
    always @(posedge wr_clk)if(accepted && packet_ok)memory[int'(write_bank)*PIXELS+int'(write_index)]<=in_rgb;
    always @(posedge pix_clk or negedge arst_n)begin
        if(!arst_n)begin
            request_sync<=0;wr_alive<=0;ack_toggle<=0;show_valid<=0;show_bank<=0;show_frame<=0;
            x<=0;y<=0;rgb<=0;de<=0;hsync<=1;vsync<=1;frame_valid<=0;frame_id<=0;
        end else begin
            request_sync<={request_sync[0],request_toggle};wr_alive<={wr_alive[0],wr_up};
            if(!pixel_running)begin x<=0;y<=0;rgb<=0;de<=0;hsync<=1;vsync<=1;frame_valid<=0;end
            else begin
                if(take_pending)begin
                    show_valid<=1;show_bank<=published_bank;show_frame<=published_frame;ack_toggle<=request_sync[1];
                end
                de<=active;
                hsync<=!(int'(x)>=WIDTH+H_FP && int'(x)<WIDTH+H_FP+H_SYNC);
                vsync<=!(int'(y)>=HEIGHT+V_FP && int'(y)<HEIGHT+V_FP+V_SYNC);
                frame_valid<=active && selected_valid;frame_id<=selected_frame;
                if(active && selected_valid)
                    rgb<=memory[int'(read_bank)*PIXELS+read_index];
                else rgb<=0;
                if(x==XW'(HT-1))begin x<=0;y<=y==YW'(VT-1) ? '0:y+1'b1;end
                else x<=x+1'b1;
            end
        end
    end
endmodule
