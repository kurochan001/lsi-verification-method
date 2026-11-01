// Two complete-frame slots. RX has no ready: admission is fixed at the first byte.
// A full/oversized frame is discarded through LAST, even if a slot opens meanwhile.
module rx_frame_queue #(parameter MAX_FRAME=128)(
    input wire clk,rst_n,rx_valid,rx_last,rx_error,input wire [7:0] rx_data,
    output wire frame_valid,input wire frame_ready,
    output wire [8*MAX_FRAME-1:0] frame_data,output wire [15:0] frame_length,
    output wire frame_error,output reg [1:0] occupancy,
    output reg [31:0] accepted,full_drops,long_drops
);
    reg [7:0] memory[0:1][0:MAX_FRAME-1];
    reg [15:0] lengths[0:1];reg errors[0:1];
    reg head,tail,in_frame,link_bad;
    reg [1:0] discard;
    integer used;
    wire pop=frame_valid && frame_ready;
    wire [1:0] reason=in_frame ? discard : (occupancy==2 && !pop ? 2'd1 : 2'd0);
    wire [31:0] index=in_frame ? 32'(used) : 32'd0;
    wire push=rx_valid && rx_last && reason==0 && index<MAX_FRAME;
    assign frame_valid=rst_n && occupancy!=0;
    assign frame_length=lengths[head];assign frame_error=errors[head];
    for(genvar i=0;i<MAX_FRAME;i=i+1)begin:read_bytes
        assign frame_data[8*i+:8]=memory[head][i];
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            head<=0;tail<=0;in_frame<=0;link_bad<=0;discard<=0;used<=0;occupancy<=0;
            accepted<=0;full_drops<=0;long_drops<=0;
            lengths[0]<=0;lengths[1]<=0;errors[0]<=0;errors[1]<=0;
        end else begin
            case({push,pop})2'b10:occupancy<=occupancy+1'b1;2'b01:occupancy<=occupancy-1'b1;default:;endcase
            if(pop)head<=!head;
            if(rx_valid)begin
                if(reason==0 && index<MAX_FRAME)memory[tail][index]<=rx_data;
                if(rx_last)begin
                    in_frame<=0;used<=0;discard<=0;link_bad<=0;
                    if(reason==1)full_drops<=full_drops+1'b1;
                    else if(reason==2 || index>=MAX_FRAME)long_drops<=long_drops+1'b1;
                    else begin
                        lengths[tail]<=16'(index+1);errors[tail]<=(in_frame && link_bad)||rx_error;
                        tail<=!tail;accepted<=accepted+1'b1;
                    end
                end else begin
                    in_frame<=1;used<=index<MAX_FRAME ? int'(index)+1 : MAX_FRAME+1;link_bad<=(in_frame && link_bad)||rx_error;
                    discard<=reason!=0 ? reason : (index>=MAX_FRAME ? 2'd2 : 2'd0);
                end
            end
        end
    end
endmodule
