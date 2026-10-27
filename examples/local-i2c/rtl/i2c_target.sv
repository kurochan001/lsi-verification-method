// Single-byte register target. Digital open-drain teaching model, not an I2C IP.
module i2c_target #(parameter ADDRESS=7'h42,MUTATION=0)(
    input wire clk,rst_n,reject_data,
    input wire [7:0] stretch_cycles,
    inout wire scl,sda,
    output reg [7:0] value
);
    localparam IDLE=0,ADDRESS_BITS=1,RECEIVE=2,ACK=3,TRANSMIT=4,MASTER_ACK=5,WAIT_STOP=6;
    reg scl_low,sda_low;
    assign scl=scl_low ? 1'b0 : 1'bz;
    assign sda=sda_low ? 1'b0 : 1'bz;
    reg scl_meta,scl_sync,scl_previous,sda_meta,sda_sync,sda_previous;
    wire rise=scl_sync && !scl_previous, fall=!scl_sync && scl_previous;
    wire start_seen=scl_sync && sda_previous && !sda_sync;
    wire stop_seen=scl_sync && !sda_previous && sda_sync;
    integer state,next_state,bits,tx_index,stretch_remaining;
    reg [7:0] shift,pending;
    reg ack_wanted,ack_started,ack_seen,commit_pending;
    always @(posedge clk) begin
        if(!rst_n) begin
            scl_meta<=1;scl_sync<=1;scl_previous<=1;
            sda_meta<=1;sda_sync<=1;sda_previous<=1;
            scl_low<=0;sda_low<=0;value<=0;state<=IDLE;next_state<=IDLE;
            bits<=0;tx_index<=7;stretch_remaining<=0;shift<=0;pending<=0;
            ack_wanted<=0;ack_started<=0;ack_seen<=0;commit_pending<=0;
        end else begin
            scl_meta<=scl;scl_sync<=scl_meta;scl_previous<=scl_sync;
            sda_meta<=sda;sda_sync<=sda_meta;sda_previous<=sda_sync;
            if(stretch_remaining>0) begin
                stretch_remaining<=stretch_remaining-1;
                if(stretch_remaining==1) scl_low<=0;
            end
            if(start_seen && !(MUTATION==4 && state!=IDLE)) begin
                state<=ADDRESS_BITS;bits<=0;shift<=0;sda_low<=0;
                ack_started<=0;ack_seen<=0;commit_pending<=0;
            end else if(stop_seen) begin
                state<=IDLE;sda_low<=0;scl_low<=0;stretch_remaining<=0;
            end else case(state)
                ADDRESS_BITS,RECEIVE: if(rise) begin
                    shift<={shift[6:0],sda_sync};
                    if(bits==7) begin
                        state<=ACK;ack_started<=0;ack_seen<=0;bits<=0;
                        pending<={shift[6:0],sda_sync};
                        if(state==ADDRESS_BITS) begin
                            ack_wanted<=shift[6:0]==ADDRESS || MUTATION==3;
                            commit_pending<=0;
                            next_state<=(shift[6:0]==ADDRESS || MUTATION==3) ?
                                         (sda_sync ? TRANSMIT : RECEIVE) : WAIT_STOP;
                        end else begin
                            ack_wanted<=!reject_data;commit_pending<=!reject_data;
                            next_state<=WAIT_STOP;
                        end
                    end else bits<=bits+1;
                end
                ACK: begin
                    if(fall && !ack_started) begin
                        ack_started<=1;sda_low<=ack_wanted;
                        if(ack_wanted && stretch_cycles!=0 && MUTATION!=2) begin
                            scl_low<=1;stretch_remaining<=stretch_cycles;
                        end
                    end else if(rise && ack_started) begin
                        ack_seen<=1;
                        if(commit_pending && ack_wanted)
                            value<=pending;
                    end else if(fall && ack_seen) begin
                        state<=next_state;sda_low<=0;shift<=0;bits<=0;
                        if(next_state==TRANSMIT) begin tx_index<=7;sda_low<=!value[7];end
                    end
                end
                TRANSMIT: begin
                    if(rise && tx_index==0) begin state<=MASTER_ACK;ack_started<=0;end
                    else if(fall && tx_index>0) begin tx_index<=tx_index-1;sda_low<=!(value[tx_index-1] ^ (MUTATION==1 && tx_index==1));end
                end
                MASTER_ACK: begin
                    if(fall) begin sda_low<=0;ack_started<=1;end
                    if(rise && ack_started) state<=WAIT_STOP;
                end
                default: begin end
            endcase
        end
    end
endmodule
