// Round-robin service with a fixed execution delay and a backpressured response.
module bounded_server #(parameter SERVICE=1,MUTATION=0)(
 input wire clk,rst_n,input wire [1:0] request,output wire [1:0] accept,
 output wire response_valid,output reg response_owner,input wire response_ready,
 output wire active,executing,responding,output wire [7:0] service_remaining
);
 reg [1:0] state;reg next_owner;reg [7:0] remaining;
 wire chosen=(MUTATION==1) ? !request[0] : request[next_owner] ? next_owner:!next_owner;
 assign accept=rst_n && state==0 && |request ? (chosen ? 2'b10:2'b01):0;
 assign response_valid=rst_n && state==2;
 assign active=state!=0;assign executing=state==1;assign responding=state==2;assign service_remaining=remaining;
 always @(posedge clk)begin
  if(!rst_n)begin state<=0;next_owner<=0;remaining<=0;response_owner<=0;end
  else case(state)
   0:if(|accept)begin response_owner<=chosen ^ (MUTATION==4);remaining<=SERVICE-1;state<=1;end
   1:if(MUTATION!=3)begin if(remaining==0)state<=2;else remaining<=remaining-1'b1;end
   2:if(response_ready || MUTATION==2)begin state<=0;next_owner<=!response_owner;end
   default:state<=0;
  endcase
 end
endmodule
