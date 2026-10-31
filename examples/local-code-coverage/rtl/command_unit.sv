// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
module command_unit #(parameter WIDTH=8,MUTATION=0)(
 input wire clk,rst_n,req_valid,operation,enable,authorized,
 input wire [WIDTH-1:0] a,b,output wire req_ready,
 output wire resp_valid,input wire resp_ready,
 output reg [WIDTH-1:0] result,output reg error
);
 typedef enum logic [1:0] {IDLE,EXEC,RESP,DENY} state_t;
 state_t state /*verilator fsm_state*/ /*verilator fsm_reset_arc*/ /*verilator fsm_arc_include_cond*/;
 wire reset=!rst_n;
 reg saved_operation;
 reg [WIDTH-1:0] operand_a,operand_b;
 assign req_ready=rst_n && state==IDLE;
 assign resp_valid=rst_n && state==RESP;
 always_ff @(posedge clk)begin
  if(reset)state<=IDLE;
  else begin
   case(state)
    IDLE:if(req_valid)begin
     if(enable && authorized)state<=EXEC; // CC_PERMISSION
     else state<=DENY;
    end else state<=IDLE;
    EXEC:state<=RESP;
    DENY:state<=RESP;
    RESP:if(resp_ready)state<=IDLE;else state<=RESP;
    default:state<=IDLE;
   endcase
  end
 end
 always_ff @(posedge clk)begin
  if(!rst_n)begin
   result<=0;error<=0;saved_operation<=0;operand_a<=0;operand_b<=0;
  end else begin
   if(state==IDLE && req_valid)begin
    operand_a<=a;operand_b<=b;saved_operation<=operation;error<=0;
   end
   if(state==EXEC)begin
    if(saved_operation)
     result<=(operand_a ^ operand_b)^WIDTH'(MUTATION); // CC_XOR
    else
     result<=(operand_a + operand_b)^WIDTH'(MUTATION); // CC_ADD
   end
   if(state==DENY)begin result<=0;error<=1;end
  end
 end
endmodule
