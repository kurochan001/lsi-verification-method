module liveness_formal #(parameter MUTATION=0, FAIR=1, COVER_MODE=0)(
 input wire clk,rst_n,input wire [1:0] request,input wire enable,choose
);
 wire [1:0] ready,grant,pending;wire turn;
 fair_arbiter #(.MUTATION(MUTATION)) dut(clk,rst_n,request,enable,ready,grant,pending,turn);
 reg past_valid=0;
 (* keep *) reg owed=0,active=0,fair_seen=0;
 (* keep *) wire [3:0] state={turn,pending,owed};
 (* keep *) reg [3:0] snapshot=0;
 always @(posedge clk)begin
  past_valid<=1;
  as_initial_reset:assume(rst_n==past_valid);
  as_request_contract:assume((request & ~ready)==0);
  if(!rst_n)begin owed<=0;active<=0;fair_seen<=0;end
  else begin
   if(request[1] && ready[1])owed<=1;
   else if(grant[1])owed<=0;
   if(grant[1] || !owed)begin active<=0;fair_seen<=0;end
   else if(!active)begin
    if(choose)begin active<=1;snapshot<=state;fair_seen<=enable;end
   end else begin
    // A return to the complete relevant state closes a non-empty bad loop.
    // A fair closed walk has an enable opportunity; no fixed deadline is assumed.
    if(COVER_MODE==0)ap_no_fair_lasso:assert(!(state==snapshot && (FAIR==0 || fair_seen)));
    fair_seen<=fair_seen|enable;
   end
  end
 end
 generate if(COVER_MODE!=0)begin: reachability
  reg [4:0] stalled=0;
  always @(posedge clk)begin
   if(!rst_n || enable || !owed)stalled<=0;
   else if(stalled<16)stalled<=stalled+1'b1;
   cp_request:cover(past_valid && owed && &pending);
   cp_completion:cover(past_valid && owed && grant[1]);
   cp_long_wait:cover(past_valid && stalled==16 && owed);
  end
 end endgenerate
endmodule
