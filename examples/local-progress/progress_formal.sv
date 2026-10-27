module progress_formal #(parameter SERVICE=1,READY_GAP=2,MUTATION=0,FAIR=1,FORCE_STALL=0,CHECK_DEADLINES=1,AUXILIARY=1)(
 input wire clk,rst_n,input wire [1:0] request,input wire response_ready
);
 localparam COMPLETE_BOUND=SERVICE+READY_GAP+2;
 localparam ACCEPT_BOUND=2*(SERVICE+READY_GAP+3);
 wire [1:0] accept;wire response_valid,response_owner,active,executing,responding;wire [7:0] service_remaining;
 bounded_server #(.SERVICE(SERVICE),.MUTATION(MUTATION)) dut(.*);
 reg past_valid=0,pending,owner,recovering=0;integer age,wait0,wait1,stall_count;
 always @(posedge clk)begin
  past_valid<=1;
  if(!past_valid)as_initial_reset:assume(!rst_n);
  if(past_valid && rst_n && $past(rst_n))begin
   if($past(request[0] && !accept[0]))as_hold0:assume(request[0]);
   if($past(request[1] && !accept[1]))as_hold1:assume(request[1]);
  end
  if(!rst_n)begin
   pending<=0;owner<=0;age<=0;wait0<=0;wait1<=0;stall_count<=0;
   if(past_valid && pending)recovering<=1;
  end else begin
   if(response_ready)stall_count<=0;else if(stall_count<READY_GAP)stall_count<=stall_count+1;
   if(pending && age<=ACCEPT_BOUND+2)age<=age+1;
   if(response_valid && response_ready)begin pending<=0;age<=0;recovering<=0;end
   if(|accept)begin pending<=1;owner<=accept[1];age<=0;end
   if(!request[0] || accept[0])wait0<=0;else if(wait0<=ACCEPT_BOUND+1)wait0<=wait0+1;
   if(!request[1] || accept[1])wait1<=0;else if(wait1<=ACCEPT_BOUND+1)wait1<=wait1+1;
  end
  if(past_valid && rst_n)begin
   ap_owner:assert(!response_valid || (pending && response_owner==owner));
   ap_exclusive:assert(accept!=3);
   if($past(rst_n && response_valid && !response_ready))ap_hold:assert(response_valid && response_owner==$past(response_owner));
   cp_contention:cover(request==3);
   cp_stall:cover(response_valid && !response_ready);
   cp_done0:cover(response_valid && response_ready && !response_owner);
   cp_done1:cover(response_valid && response_ready && response_owner);
   cp_wait:cover(wait0>READY_GAP || wait1>READY_GAP);
   cp_recovery:cover(recovering && response_valid && response_ready);
  end
  if(past_valid)cp_reset_pending:cover(!rst_n && pending);
 end
 generate if(FAIR)always @(posedge clk)if(rst_n)as_receiver_fair:assume(response_ready || stall_count<READY_GAP-1);endgenerate
 generate if(FORCE_STALL)always @(posedge clk)if(rst_n)as_no_receiver:assume(!response_ready);endgenerate
 generate if(CHECK_DEADLINES)begin
  always @(posedge clk)if(past_valid && rst_n)begin
   ap_completion:assert(!pending || age<=COMPLETE_BOUND);
   ap_accept:assert(wait0<=ACCEPT_BOUND && wait1<=ACCEPT_BOUND);
  end
 end endgenerate
 generate if(AUXILIARY)begin
  always @(posedge clk)if(past_valid && rst_n)begin
   ai_ledger:assert(pending==active);
   ai_owner:assert(!active || response_owner==owner);
   ai_counter:assert(service_remaining<SERVICE);
   ai_state:assert(active==(executing || responding));
   ai_nonnegative:assert(age>=0 && age<=ACCEPT_BOUND+3 && wait0>=0 && wait0<=ACCEPT_BOUND+2 && wait1>=0 && wait1<=ACCEPT_BOUND+2 && stall_count>=0 && stall_count<=READY_GAP);
  end
  if(FAIR)always @(posedge clk)if(past_valid && rst_n)begin
   ai_fair_counter:assert(stall_count<READY_GAP);
   ai_timing:assert((!executing || age+int'(service_remaining)==SERVICE-1) && (!responding || age<=SERVICE+stall_count));
  end
 end endgenerate
endmodule
