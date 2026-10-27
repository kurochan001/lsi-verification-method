// Shift-register reference and circular-buffer implementation with the same cycle contract.
module fifo_gold #(parameter DEPTH=2,WIDTH=4)(
 input wire clk,rst_n,valid,ready,input wire [WIDTH-1:0] data,
 output wire in_ready,out_valid,output wire [WIDTH-1:0] out_data,
 output reg [$clog2(DEPTH):0] count,output wire [WIDTH*DEPTH-1:0] contents
);
 reg [WIDTH-1:0] queue[0:DEPTH-1];
 wire push=valid&&in_ready,pop=ready&&out_valid;
 assign in_ready=count<DEPTH;assign out_valid=count!=0;assign out_data=queue[0];
 genvar g;generate for(g=0;g<DEPTH;g=g+1)assign contents[g*WIDTH+:WIDTH]=queue[g];endgenerate
 always @(posedge clk)begin
  if(!rst_n)begin count<=0;for(integer i=0;i<DEPTH;i=i+1)queue[i]<=0;end
  else begin
   if(pop)for(integer i=0;i<DEPTH-1;i=i+1)queue[i]<=queue[i+1];
   if(push)queue[count-(pop ? 1:0)]<=data;
   count<=count+push-pop;
  end
 end
endmodule
module fifo_optimized #(parameter DEPTH=2,WIDTH=4,MUTATION=0)(
 input wire clk,rst_n,valid,ready,input wire [WIDTH-1:0] data,
 output wire in_ready,out_valid,output wire [WIDTH-1:0] out_data,
 output reg [$clog2(DEPTH):0] count,output wire [WIDTH*DEPTH-1:0] contents,
 output reg [$clog2(DEPTH)-1:0] head,tail
);
 reg [WIDTH-1:0] memory[0:DEPTH-1];wire push=valid&&in_ready,pop=ready&&out_valid;
 assign in_ready=MUTATION==3 ? 1'b1:count<DEPTH;assign out_valid=count!=0;
 assign out_data=memory[MUTATION==2 ? tail:head] ^ (MUTATION==4 ? {{(WIDTH-1){1'b0}},1'b1}:0);
 genvar g;generate for(g=0;g<DEPTH;g=g+1)assign contents[g*WIDTH+:WIDTH]=memory[g];endgenerate
 always @(posedge clk)begin
  if(!rst_n)begin count<=0;head<=0;tail<=0;for(integer i=0;i<DEPTH;i=i+1)memory[i]<=0;end
  else begin
   if(push)begin memory[tail]<=data;tail<=tail+1'b1;end
   if(pop)head<=head+1'b1;
   count<=count+push-(pop && !(MUTATION==1 && push));
  end
 end
endmodule
