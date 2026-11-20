// A command unit with three kinds of code that a base test leaves unhit:
// GU_DENY and GU_STALL can be reached, GU_GUARD can never be reached,
// GU_TEST can be reached only outside the functional mode.
module guarded_unit #(parameter WIDTH=4)(
 input wire clk,rst_n,test_mode,req_valid,enable,authorized,
 input wire [WIDTH-1:0] a,b,
 output wire req_ready,resp_valid,
 input wire resp_ready,
 output reg [WIDTH-1:0] result,
 output reg error,stalled,fault
);
 localparam [1:0] IDLE=2'd0,EXEC=2'd1,RESP=2'd2,DENY=2'd3;
 localparam [3:0] LIMIT=4'd12;   // response cycles without resp_ready before stalled is set
 reg [1:0] state;
 reg [3:0] held;                 // cleared when a response is taken, not while idle
 reg [WIDTH-1:0] operand_a,operand_b;
 assign req_ready=rst_n && state==IDLE;
 assign resp_valid=rst_n && state==RESP;
 always @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;result<={WIDTH{1'b0}};error<=1'b0;stalled<=1'b0;fault<=1'b0;held<=4'd0;
   operand_a<={WIDTH{1'b0}};operand_b<={WIDTH{1'b0}};
  end else begin
   case(state)
    IDLE:if(req_valid)begin
     error<=1'b0;stalled<=1'b0;operand_a<=a;operand_b<=b;
     if(test_mode)begin result<={WIDTH{1'b1}};state<=RESP;end   // GU_TEST
     else if(enable && authorized)state<=EXEC;
     else state<=DENY;
    end
    EXEC:begin result<=operand_a+operand_b;state<=RESP;end
    DENY:begin result<={WIDTH{1'b0}};error<=1'b1;state<=RESP;end   // GU_DENY
    RESP:begin
     if(held>=LIMIT)fault<=1'b1;                                   // GU_GUARD
     if(resp_ready)begin state<=IDLE;held<=4'd0;end
     else if(held==LIMIT-4'd1)stalled<=1'b1;                       // GU_STALL
     else held<=held+4'd1;
    end
   endcase
  end
 end
endmodule
