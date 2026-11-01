// Store-and-forward echo. Queueing is independent of the backpressured TX stream.
module network_echo #(parameter MAX_FRAME=128,MUTATION=0)(
    input wire clk,rst_n,rx_valid,rx_last,rx_error,input wire [7:0] rx_data,
    output wire tx_valid,tx_last,output wire [7:0] tx_data,input wire tx_ready,
    output wire [1:0] occupancy,output wire [31:0] accepted,full_drops,long_drops,
    output reg [31:0] rejected,transmitted,output reg [3:0] last_drop
);
    wire frame_valid,frame_ready,frame_error,accept;
    wire [8*MAX_FRAME-1:0] frame_data,reply_data;
    wire [15:0] frame_length,reply_length;
    wire [1:0] kind;wire [3:0] drop_reason;
    reg active;reg [8*MAX_FRAME-1:0] packet;
    reg [15:0] length;integer index;
    rx_frame_queue #(.MAX_FRAME(MAX_FRAME)) queue(.*);
    packet_codec #(.MAX_FRAME(MAX_FRAME),.MUTATION(MUTATION)) codec(
        .valid(frame_valid),.frame_data(frame_data),.frame_length(frame_length),.frame_error(frame_error),
        .accept(accept),.kind(kind),.drop_reason(drop_reason),.reply_data(reply_data),.reply_length(reply_length));
    assign frame_ready=!active;
    assign tx_valid=rst_n && active;assign tx_data=packet[8*index+:8];assign tx_last=index==int'(length)-1;
    // Kind is metadata for the standalone echo; the frame bytes are the observable result.
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_kind=&{1'b0,kind};
    /* verilator lint_on UNUSEDSIGNAL */
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin active<=0;packet<=0;length<=0;index<=0;rejected<=0;transmitted<=0;last_drop<=0;end
        else begin
            if(frame_valid && frame_ready)begin
                if(accept)begin active<=1;packet<=reply_data;length<=reply_length;index<=0;end
                else begin rejected<=rejected+1'b1;last_drop<=drop_reason;end
            end
            if(tx_valid && (tx_ready || MUTATION==4))begin
                if(tx_last)begin active<=0;transmitted<=transmitted+1'b1;end
                else index<=index+1;
            end
        end
    end
endmodule
