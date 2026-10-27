// Digital sequencing model. gate_en changes only while clk is low.
module clock_reset #(parameter MUTATION=0,STAGES=2,LATENCY=3)(
 input wire clk,rst_n,core_reset_n,stop_req,wake_req,req_valid,input wire [7:0] req_data,
 output wire req_ready,stopped,clock_enabled,reset_released,output reg [7:0] result,output reg [15:0] completed
);
 localparam RUN=0,DRAIN=1,STOP=2,WAKE=3;reg [1:0] state;reg gate_en;
 wire work_clk=clk && gate_en;wire reset_async=rst_n && core_reset_n;
 reg [STAGES-1:0] release_pipe;integer remaining;reg [7:0] operand;
 wire pending=remaining!=0;
 assign reset_released=MUTATION==2 ? reset_async:release_pipe[STAGES-1];
 assign req_ready=rst_n && reset_released && state==RUN && (!stop_req || MUTATION==4) && !pending;
 assign stopped=state==STOP;assign clock_enabled=gate_en;
 always @(negedge clk or negedge rst_n)begin if(!rst_n)gate_en<=1;else gate_en<=state!=STOP;end
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)state<=RUN;
 else case(state)
 RUN:if(stop_req)state<=DRAIN;
 DRAIN:if(!pending || MUTATION==1)state<=STOP;
 STOP:if(wake_req)state<=WAKE;
 WAKE:if(reset_released)state<=RUN;
 endcase
 end
 always @(posedge work_clk or negedge reset_async)begin
 if(!reset_async)release_pipe<=0;else release_pipe<={release_pipe[STAGES-2:0],1'b1};
 end
 always @(posedge work_clk or negedge reset_async)begin
 if(!reset_async)begin remaining<=0;operand<=0;result<=0;completed<=0;end
 else if(!reset_released)begin remaining<=0;operand<=0;result<=0;completed<=0;end
 else begin
 if(remaining>0)begin
 remaining<=remaining-1;
 if(remaining==1)begin result<=result+operand;completed<=completed+1'b1;end
 end
 if(req_valid && req_ready)begin operand<=req_data;remaining<=LATENCY;end
 if(MUTATION==3 && state==WAKE)result<=0;
 end end
endmodule
