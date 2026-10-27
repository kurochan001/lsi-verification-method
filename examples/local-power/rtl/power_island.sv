// Behavioral power sequencing, not a UPF/supply or clock-cell implementation.
module power_island #(parameter LATENCY=2,MUTATION=0)(
 input wire clk,rst_n,sleep_req,wake_req,retain,req_valid,input wire [7:0] req_data,
 output wire req_ready,power_good,isolate,clock_enable,sleep_ack,
 output reg done,output wire [7:0] result
);
 localparam ON=0,DRAIN=1,SAVE=2,ISO=3,OFF=4,WAKE=5,RESTORE=6;
 reg [2:0] state;reg keep,pending;integer remaining;
 reg [7:0] accumulator,saved,operand;
 assign req_ready=rst_n && ((state==ON && !sleep_req && !pending) || (MUTATION==4 && state==DRAIN));
 assign power_good=state!=OFF;
 assign isolate=(state>=ISO) && !(MUTATION==3 && state==OFF);
 assign clock_enable=state!=OFF;assign sleep_ack=state==OFF;
 assign result=isolate ? 8'b0:accumulator;
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n)begin state<=ON;keep<=0;pending<=0;remaining<=0;accumulator<=0;saved<=0;operand<=0;done<=0;end
  else begin
   done<=0;
   if(pending && power_good)begin
    if(remaining==0)begin accumulator<=accumulator+operand;pending<=0;done<=1;end
    else remaining<=remaining-1;
   end
   if(req_valid && req_ready)begin operand<=req_data;pending<=1;remaining<=LATENCY;end
   case(state)
    ON:if(sleep_req)begin state<=MUTATION==1 ? ISO:DRAIN;keep<=retain;end
    DRAIN:if(!pending)state<=SAVE;
    SAVE:begin if(keep)saved<=accumulator;state<=ISO;end
    ISO:state<=OFF;
    OFF:begin accumulator<=8'hxx;if(wake_req)state<=WAKE;end
    WAKE:begin accumulator<=0;state<=RESTORE;end
    RESTORE:begin accumulator<=keep && MUTATION!=2 ? saved:0;state<=ON;end
    default:state<=ON;
   endcase
  end
 end
endmodule
