module equivalence_formal #(parameter DEPTH=2,WIDTH=4,MUTATION=0,AUXILIARY=1,LOCK_RESET=0)(
 input wire clk,rst_n,valid,ready,input wire [WIDTH-1:0] data
);
 wire gi,gv,oi,ov;wire [WIDTH-1:0] gd,od;wire [$clog2(DEPTH):0] gc,oc;
 wire [WIDTH*DEPTH-1:0] gold,optimized;wire [$clog2(DEPTH)-1:0] head,tail;
 fifo_gold #(.DEPTH(DEPTH),.WIDTH(WIDTH)) reference_fifo(clk,rst_n,valid,ready,data,gi,gv,gd,gc,gold);
 fifo_optimized #(.DEPTH(DEPTH),.WIDTH(WIDTH),.MUTATION(MUTATION)) implementation(clk,rst_n,valid,ready,data,oi,ov,od,oc,optimized,head,tail);
 reg past_valid=0,recovering=0;reg mapping_ok;integer index;
 always @*begin
  mapping_ok=1;
  for(integer i=0;i<DEPTH;i=i+1)begin
   index=(head+i)%DEPTH;
   if(i<gc && gold[i*WIDTH+:WIDTH]!=optimized[index*WIDTH+:WIDTH])mapping_ok=0;
  end
 end
 always @(posedge clk)begin
  past_valid<=1;
  if(!past_valid)as_initial_reset:assume(!rst_n);
  if(!rst_n && past_valid && gc!=0)recovering<=1;
  if(rst_n && gv && ready)recovering<=0;
  if(past_valid)begin
   ap_control:assert({gi,gv}=={oi,ov});
   if(gv)ap_data:assert(gd==od);
   cp_full:cover(rst_n && !gi);
   cp_drain:cover(rst_n && gv && ready && gc==1);
   cp_simultaneous:cover(rst_n && valid && gi && ready && gv);
   cp_reset_pending:cover(!rst_n && gc!=0);
   cp_recovery:cover(rst_n && recovering && gv && ready);
  end
 end
 generate if(AUXILIARY)begin
  always @(posedge clk)if(past_valid)begin
   ai_count:assert(gc==oc && gc<=DEPTH);
   ai_pointer:assert(tail==(head+oc)%DEPTH);
   ai_mapping:assert(mapping_ok);
  end
 end endgenerate
 generate if(LOCK_RESET)always @(posedge clk)as_lock_reset:assume(!rst_n);endgenerate
endmodule
