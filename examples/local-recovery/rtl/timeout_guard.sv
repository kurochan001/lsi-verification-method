// Tagged request/response wrapper. Timeout is local policy, not AXI cancellation.
module timeout_guard #(parameter TIMEOUT=4,TAG_BITS=4,MUTATION=0)(
 input wire clk,rst_n,u_valid,u_ready_response,input wire [7:0] u_data,
 output wire u_ready,output reg u_response,u_error,output reg [7:0] u_result,
 output wire d_valid,input wire d_ready,output wire [7:0] d_data,output wire [15:0] d_tag,
 input wire d_response,input wire [15:0] response_tag,input wire [7:0] response_data,
 output wire response_ready,output reg late_dropped
);
 localparam IDLE=0,SEND=1,WAIT=2,RETURN=3;
 reg [1:0] state;reg [TAG_BITS-1:0] serial;reg [15:0] active_tag;reg [7:0] saved;integer age;
 assign u_ready=rst_n && state==IDLE && !(&serial);
 assign d_valid=rst_n && state==SEND;assign d_tag=active_tag;assign d_data=saved;
 assign response_ready=rst_n;
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin state<=IDLE;serial<=0;active_tag<=0;saved<=0;age<=0;u_response<=0;u_error<=0;u_result<=0;late_dropped<=0;end
  else begin
   late_dropped<=0;
   if(d_response && !(state==WAIT && response_tag==active_tag))late_dropped<=1;
   if(u_response && (u_ready_response || MUTATION==4))begin u_response<=0;state<=IDLE;end
   case(state)
    IDLE:if(u_valid && u_ready)begin
     serial<=serial+1'b1;active_tag<=MUTATION==3 ? 0:serial+1'b1;saved<=u_data;state<=SEND;
    end
    SEND:if(d_ready)begin state<=WAIT;age<=0;end
    WAIT:begin
     if(d_response && (response_tag==active_tag || MUTATION==1))begin
      u_response<=1;u_error<=0;u_result<=response_data;state<=RETURN;
     end else if(age==(MUTATION==2 ? TIMEOUT:TIMEOUT-1))begin
      u_response<=1;u_error<=1;u_result<=0;state<=RETURN;
     end else age<=age+1;
    end
    default:;
   endcase
  end
 end
endmodule
