// One captured FP32 vector -> 4 FP16 beats, 2 MXFP8 beats, or 1 MXFP4 beat.
module mp_encoder(
  input logic clk,rst_n,in_valid,out_ready,
  input logic [1:0] mode,
  input logic [1023:0] values,
  output logic in_ready,out_valid,out_last,err_mode,
  output logic [1:0] out_mode,
  output logic [135:0] block_data
);
  import mp_pkg::*;
  logic [511:0] packed_data,payload;
  logic [7:0] scale4,scale8,scale_reg;
  logic special,all_zero;
  integer maximum_exp;
  logic [1:0] index;
  logic [2:0] total;
  logic [2:0] mag4 [32];
  logic signed [9:0] rel4 [32];
  for(genvar i=0;i<32;i++) begin: fp4_quant
    assign rel4[i]=$signed({2'b0,values[32*i+23 +: 8]})-$signed({2'b0,scale4});
    e2m1_quantize quant(.e_rel_i(rel4[i]),.frac_i(values[32*i +: 23]),
      .is_zero_i(values[32*i+23 +: 8]==0),.mag3_o(mag4[i]));
  end
  always_comb begin
    maximum_exp=0;special=0;all_zero=1;
    for(integer i=0;i<32;i++) begin
      if(integer'(values[32*i+23 +: 8])>maximum_exp) maximum_exp=integer'(values[32*i+23 +: 8]);
      if(values[32*i+23 +: 8]==255) special=1;
      if(values[32*i+23 +: 8]!=0) all_zero=0;
    end
    scale4=maximum_exp<2 ? 0 : 8'(maximum_exp-2);
    scale8=maximum_exp<8 ? 0 : 8'(maximum_exp-8);
    packed_data=0;
    for(integer i=0;i<32;i++) begin
      if(mode==FP16) packed_data[16*i +: 16]=fp16_cast(values[32*i +: 32]);
      else if(!special && !all_zero) begin
        if(mode==FP8) packed_data[8*i +: 8]=quantize_e4m3(values[32*i +: 32],scale8);
        else packed_data[4*i +: 4]={values[32*i+31],mag4[i]};
      end
    end
    block_data={out_mode==FP16 ? 8'b0 : scale_reg,payload[128*integer'(index) +: 128]};
    out_last=out_valid && ({1'b0,index}==total-1'b1);
  end
  assign in_ready=rst_n && !out_valid && mode!=3;
  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin out_valid<=0;out_mode<=FP4;payload<=0;scale_reg<=0;index<=0;total<=1;err_mode<=0;end
    else begin
      if(in_valid && mode==3 && !out_valid) err_mode<=1;
      if(in_valid && in_ready) begin
        out_valid<=1;out_mode<=mode;payload<=packed_data;index<=0;
        total<=mode==FP16 ? 4 : mode==FP8 ? 2 : 1;
        scale_reg<=special ? 8'hff : all_zero ? 8'b0 : mode==FP8 ? scale8 : scale4;
        err_mode<=0;
      end else if(out_valid && out_ready) begin
        if(out_last) out_valid<=0;
        else index<=index+1'b1;
      end
    end
  end
  a_output_hold: assert property (@(posedge clk) disable iff(!rst_n)
    out_valid && !out_ready |=> out_valid && $stable({block_data,out_mode,out_last}))
    else $fatal(1,"MP_ENCODER_OUTPUT_HOLD");
endmodule
