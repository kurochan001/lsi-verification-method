// Direct form I biquad: y = Q(b0*x + b1*x1 + b2*x2 - a1*y1 - a2*y2), then saturate or wrap.
// Coefficients are signed words with FRAC fractional bits. ROUND: 0 floor, 1 nearest (ties up),
// 2 toward zero. SAT: 1 saturate, 0 two's-complement wrap. One sample per accepted handshake.
module iir_biquad #(parameter FRAC=14,ROUND=1,SAT=1,MUTATION=0)(
 input wire clk,rst_n,clear,
 input wire cfg_we,input wire [2:0] cfg_addr,input wire signed [15:0] cfg_data,
 input wire in_valid,output wire in_ready,input wire signed [23:0] sample,
 output reg out_valid,input wire out_ready,output reg signed [23:0] result,
 output reg ovf_pos,ovf_neg
);
 localparam signed [47:0] HIGH=48'sd8388607,LOW=-48'sd8388608;
 reg signed [15:0] coef [0:4];
 reg signed [23:0] x1,x2,y1,y2;
 wire signed [47:0] b0={{32{coef[0][15]}},coef[0]},b1={{32{coef[1][15]}},coef[1]},b2={{32{coef[2][15]}},coef[2]};
 wire signed [47:0] a1={{32{coef[3][15]}},coef[3]},a2={{32{coef[4][15]}},coef[4]};
 wire signed [47:0] xe={{24{sample[23]}},sample},x1e={{24{x1[23]}},x1},x2e={{24{x2[23]}},x2};
 wire signed [47:0] y1e={{24{y1[23]}},y1},y2e={{24{y2[23]}},y2};
 wire signed [47:0] acc=b0*xe+b1*x1e+b2*x2e-a1*y1e-a2*(MUTATION==1 ? y1e:y2e);
 wire signed [47:0] half=48'sd1<<<(FRAC-1);
 wire signed [47:0] down=acc>>>FRAC,near=(acc+half)>>>FRAC,zero=acc[47] ? -((-acc)>>>FRAC):down;
 wire signed [47:0] quantized=(ROUND==0 || MUTATION==8) ? down:ROUND==1 ? near:zero;
 wire high=quantized>HIGH,low=quantized<LOW;
 wire signed [23:0] limited=(SAT!=0 && MUTATION!=7 && high) ? HIGH[23:0]:(SAT!=0 && MUTATION!=7 && low) ? LOW[23:0]:quantized[23:0];
 wire accept=in_valid && (in_ready || (MUTATION==5 && !clear));
 wire [2:0] index=MUTATION==9 ? {1'b0,cfg_addr[1:0]}:cfg_addr;
 assign in_ready=!clear && (!out_valid || out_ready || MUTATION==6);
 integer i;
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin
   for(i=0;i<5;i=i+1)coef[i]<=16'sd0;
   x1<=24'sd0;x2<=24'sd0;y1<=24'sd0;y2<=24'sd0;out_valid<=1'b0;result<=24'sd0;ovf_pos<=1'b0;ovf_neg<=1'b0;
  end else begin
   if(cfg_we && index<3'd5)coef[index]<=cfg_data;
   if(clear)begin
    x1<=24'sd0;x2<=24'sd0;out_valid<=1'b0;
    if(MUTATION!=4)begin y1<=24'sd0;y2<=24'sd0;end
   end else if(accept)begin
    x1<=sample;x2<=MUTATION==2 ? sample:x1;y1<=limited;y2<=y1;
    if(in_ready)begin result<=limited;out_valid<=1'b1;ovf_pos<=high;ovf_neg<=low && MUTATION!=3;end
   end else if(out_valid && out_ready)out_valid<=1'b0;
  end
 end
endmodule
