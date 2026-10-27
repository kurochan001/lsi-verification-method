// Two virtual channels with per-channel input queues and receiver credits.
module credit_link #(parameter MUTATION=0,DEPTH=2)(
 input wire clk,rst_n,in_valid,in_channel,input wire [7:0] in_data,input wire [1:0] credit_return,
 output wire in_ready,output reg tx_valid,tx_channel,output reg [7:0] tx_data,
 output wire [7:0] credits,queued,output reg bad_return
);
 reg [7:0] memory[0:1][0:DEPTH-1];integer head[0:1],tail[0:1],count[0:1],credit[0:1];reg turn;integer chosen;
 assign in_ready=rst_n && count[in_channel]<DEPTH;
 assign credits={4'(credit[1]),4'(credit[0])};assign queued={4'(count[1]),4'(count[0])};
 always @*begin
 chosen=-1;tx_valid=0;tx_channel=0;tx_data=0;
 if(rst_n)begin
 if(count[turn]>0 && credit[turn]>0)chosen=turn;
 else if(count[!turn]>0 && credit[!turn]>0)chosen=!turn;
 if(chosen>=0)begin tx_valid=1;tx_channel=chosen;tx_data=memory[chosen][head[chosen]] ^ (MUTATION==3 ? 8'b1:0);end
 end end
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin
 turn<=0;bad_return<=0;
 for(integer c=0;c<2;c=c+1)begin head[c]<=0;tail[c]<=0;count[c]<=0;credit[c]<=MUTATION==4 ? 0:DEPTH;end
 end else begin
 bad_return<=0;
 for(integer c=0;c<2;c=c+1)begin
 case({in_valid && in_ready && in_channel==c,tx_valid && tx_channel==c})
 2'b10:count[c]<=count[c]+1;2'b01:count[c]<=count[c]-1;default:;
 endcase
 if(in_valid && in_ready && in_channel==c)begin memory[c][tail[c]]<=in_data;tail[c]<=(tail[c]+1)%DEPTH;end
 if(tx_valid && tx_channel==c)begin head[c]<=(head[c]+1)%DEPTH;turn<=!tx_channel;end
 // A return is valid only for a credit already outstanding before this edge.
 if(credit_return[c] && credit[c]>=DEPTH)bad_return<=1;
 credit[c]<=credit[c]+int'(credit_return[MUTATION==2 ? !c:c] && credit[c]<DEPTH)-int'(tx_valid && tx_channel==c && MUTATION!=1);
 end
 end end
endmodule
