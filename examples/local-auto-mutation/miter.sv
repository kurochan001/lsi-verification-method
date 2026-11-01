module miter(input wire clk,rst_n,input wire [1:0]events,clear,mask);
 (* keep *) wire [1:0]gold_pending,mut_pending;
 (* keep *) wire gold_irq,mut_irq;
 wire [7:0]unused_gold,unused_mut;
 reference_irq gold(clk,rst_n,events,clear,mask,gold_pending,gold_irq,unused_gold);
 irq_regs mutated(clk,rst_n,events,clear,mask,mut_pending,mut_irq,unused_mut);
 reg valid=0;
 always @(posedge clk)begin
  if(!valid)as_initial_reset:assume(!rst_n);
  valid<=1;
  if(valid)ap_functional_equivalence:assert(gold_pending==mut_pending && gold_irq==mut_irq);
 end
endmodule
