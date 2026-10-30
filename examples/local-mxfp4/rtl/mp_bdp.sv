// One dot series at a time; contiguous input beats within a series are accepted.
// FP4 retains the legacy six-stage arithmetic and latency. FP8/FP16 use eight stages.
module mp_bdp(
  input logic clk,rst_n,in_valid,first,last,out_ready,
  input logic [1:0] mode,
  input logic [135:0] a_block,b_block,
  output logic in_ready,out_valid,
  output logic [31:0] result,
  output logic err_scale_mismatch,err_protocol,
  output logic signed [41:0] sum8_dbg,
  output logic sum8_valid_dbg
);
  import mp_pkg::*;
  logic [1:0] active_mode;
  logic active,draining,half,first_half_first;
  logic [7:0] first_sa,first_sb;
  logic [7:0] v,f,l,odd;
  logic en,take;
  logic signed [11:0] product4 [32];
  logic signed [13:0] partial4 [8],sum4;
  logic signed [9:0] scale4 [3];
  logic [2:0] nan4;
  logic signed [4:0] ma8 [16],mb8 [16];
  logic [4:0] shift8 [16],shift8_q [16];
  logic signed [8:0] prod8 [16];
  logic signed [41:0] aligned8 [16],partial8,sum8;
  logic [7:0] sa8 [4],sb8 [4];
  logic [3:0] nan8;
  logic [31:0] h0a [8],h0b [8],h1 [8],h2 [8];
  logic [31:0] h3 [4],h4 [2],tree_h3 [4],tree_h4 [2],tree_h5;
  term_t t4,t8_5;
  logic [31:0] t8_6,h5;
  logic [31:0] accumulator,next_acc,committed;
  logic commit_valid,output_pending;
  term_t acc_term,input_term;
  logic signed [41:0] sum16;

  assign en=!(out_valid && !out_ready);
  assign in_ready=rst_n && en && !draining && (active || mode!=3);
  assign take=in_valid && in_ready;
  assign out_valid=output_pending;
  assign sum8_dbg=sum8;
  assign sum8_valid_dbg=v[3] && odd[3] && active_mode==FP8;
  always_comb begin
    sum16=0;
    for(integer i=0;i<16;i++) sum16=sum16+aligned8[i];
    acc_term=unpack32(f[active_mode==FP4 ? 3 : 5] ? 32'b0 : accumulator);
    input_term=active_mode==FP4 ? t4 : unpack32(active_mode==FP8 ? t8_6 : h5);
  end
  mp_add accumulate(.a(acc_term),.b(input_term),.result(next_acc));
  for(genvar i=0;i<4;i++) begin: tree1
    mp_add add(.a(unpack32(h2[2*i])),.b(unpack32(h2[2*i+1])),.result(tree_h3[i]));
  end
  for(genvar i=0;i<2;i++) begin: tree2
    mp_add add(.a(unpack32(h3[2*i])),.b(unpack32(h3[2*i+1])),.result(tree_h4[i]));
  end
  mp_add tree3(.a(unpack32(h4[0])),.b(unpack32(h4[1])),.result(tree_h5));

  always_ff @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      active_mode<=FP4;active<=0;draining<=0;half<=0;first_half_first<=0;
      first_sa<=0;first_sb<=0;err_scale_mismatch<=0;err_protocol<=0;
      v<=0;f<=0;l<=0;odd<=0;nan4<=0;nan8<=0;
      sum4<=0;sum8<=0;partial8<=0;t4<='0;t8_5<='0;t8_6<=0;h5<=0;
      accumulator<=0;committed<=0;result<=0;commit_valid<=0;output_pending<=0;
      for(integer i=0;i<3;i++) scale4[i]<=0;
      for(integer i=0;i<4;i++) begin sa8[i]<=0;sb8[i]<=0;h3[i]<=0;end
      for(integer i=0;i<2;i++) h4[i]<=0;
      for(integer i=0;i<32;i++) product4[i]<=0;
      for(integer i=0;i<8;i++) begin partial4[i]<=0;h0a[i]<=0;h0b[i]<=0;h1[i]<=0;h2[i]<=0;end
      for(integer i=0;i<16;i++) begin ma8[i]<=0;mb8[i]<=0;shift8[i]<=0;shift8_q[i]<=0;prod8[i]<=0;aligned8[i]<=0;end
    end else if(en) begin
      v<={v[6:0],take};l<={l[6:0],take && last};
      f<={f[6:0],take && ((active ? active_mode : mode)==FP8 && half ? first_half_first : first)};
      odd<={odd[6:0],half};
      output_pending<=commit_valid;result<=committed;
      commit_valid<=0;
      if(out_valid && out_ready) begin active<=0;draining<=0;end
      if(in_valid && !active && mode==3) err_protocol<=1;
      if(take) begin
        if(!active) begin
          active_mode<=mode;active<=1;half<=0;
          err_scale_mismatch<=0;err_protocol<=!first;
        end else if(mode!=active_mode || first) err_protocol<=1;
        if(last) draining<=1;
        if((active ? active_mode : mode)==FP8) begin
          half<=!half;
          if(!half) begin first_sa<=a_block[135:128];first_sb<=b_block[135:128];first_half_first<=first;end
          else if(a_block[135:128]!=first_sa || b_block[135:128]!=first_sb) err_scale_mismatch<=1;
          if((!half && last)||(half && first)) err_protocol<=1;
        end else if((active ? active_mode : mode)==FP16 && (a_block[135:128]!=0 || b_block[135:128]!=0)) err_protocol<=1;
        // F1/G1/S1. Mode is captured on the first accepted beat.
        for(integer i=0;i<32;i++) product4[i]<=12'(mxfp4_pkg::e2m1_mag2(a_block[4*i +: 3])) *
          12'(mxfp4_pkg::e2m1_mag2(b_block[4*i +: 3])) * ((a_block[4*i+3]^b_block[4*i+3]) ? -12'sd1 : 12'sd1);
        scale4[0]<=10'(integer'(a_block[135:128])+integer'(b_block[135:128])-256);
        nan4[0]<=a_block[135:128]==255 || b_block[135:128]==255;
        sa8[0]<=half ? first_sa : a_block[135:128];sb8[0]<=half ? first_sb : b_block[135:128];
        nan8[0]<=(half ? first_sa : a_block[135:128])==255 || (half ? first_sb : b_block[135:128])==255;
        for(integer i=0;i<16;i++) begin
          ma8[i]<=e4m3_m(a_block[8*i +: 8]);mb8[i]<=e4m3_m(b_block[8*i +: 8]);
          shift8[i]<=5'(e4m3_e(a_block[8*i +: 8])+e4m3_e(b_block[8*i +: 8])+12);
          if(a_block[8*i +: 7]==127 || b_block[8*i +: 7]==127) nan8[0]<=1;
        end
        for(integer i=0;i<8;i++) begin h0a[i]<={16'b0,a_block[16*i +: 16]};h0b[i]<={16'b0,b_block[16*i +: 16]};end
      end
      // S2, F2, G2: exact products and FP4 partial sums.
      if(v[0]) begin
        for(integer i=0;i<8;i++) partial4[i]<=14'(product4[4*i])+14'(product4[4*i+1])+14'(product4[4*i+2])+14'(product4[4*i+3]);
        scale4[1]<=scale4[0];nan4[1]<=nan4[0];
        for(integer i=0;i<16;i++) begin prod8[i]<=ma8[i]*mb8[i];shift8_q[i]<=shift8[i];end
        for(integer i=0;i<8;i++) h1[i]<=fp16_product(h0a[i][15:0],h0b[i][15:0]);
        sa8[1]<=sa8[0];sb8[1]<=sb8[0];nan8[1]<=nan8[0];
      end
      if(v[1]) begin
        sum4<=partial4[0]+partial4[1]+partial4[2]+partial4[3]+partial4[4]+partial4[5]+partial4[6]+partial4[7];
        scale4[2]<=scale4[1];nan4[2]<=nan4[1];
        for(integer i=0;i<16;i++) aligned8[i]<=42'($signed(prod8[i])) << shift8_q[i];
        for(integer i=0;i<8;i++) h2[i]<=h1[i];
        sa8[2]<=sa8[1];sb8[2]<=sb8[1];nan8[2]<=nan8[1];
      end
      if(v[2]) begin
        t4<=normalize(64'($signed(sum4)),integer'($signed(scale4[2])));t4.nan<=nan4[2];
        for(integer i=0;i<4;i++) h3[i]<=tree_h3[i];
        if(odd[2]) begin sum8<=partial8+sum16;nan8[3]<=nan8[2] || nan8[3];end
        else begin partial8<=sum16;nan8[3]<=nan8[2];end
        sa8[3]<=sa8[2];sb8[3]<=sb8[2];
      end
      if(v[3]) begin
        for(integer i=0;i<2;i++) h4[i]<=tree_h4[i];
        t8_5<=normalize(64'($signed(sum8)),integer'(sa8[3])+integer'(sb8[3])-272);t8_5.nan<=nan8[3];
      end
      if(v[4]) begin h5<=tree_h5;t8_6<=pack_term(t8_5);end
      if((active_mode==FP4 && v[3]) || (active_mode==FP8 && v[5] && odd[5]) || (active_mode==FP16 && v[5])) begin
        accumulator<=next_acc;committed<=next_acc;
        commit_valid<=l[active_mode==FP4 ? 3 : 5];
      end
    end
  end
  a_output_hold: assert property (@(posedge clk) disable iff(!rst_n)
    out_valid && !out_ready |=> out_valid && $stable(result)) else $fatal(1,"MP_OUTPUT_HOLD");
  a_captured_mode: assert property (@(posedge clk) disable iff(!rst_n)
    active && !(out_valid && out_ready) |=> $stable(active_mode)) else $fatal(1,"MP_CAPTURED_MODE");
  a_mode_diagnostic: assert property (@(posedge clk) disable iff(!rst_n)
    take && active && mode!=active_mode |=> err_protocol) else $fatal(1,"MP_MODE_DIAGNOSTIC");
  a_scale_diagnostic: assert property (@(posedge clk) disable iff(!rst_n)
    take && active_mode==FP8 && half &&
    (a_block[135:128]!=first_sa || b_block[135:128]!=first_sb) |=> err_scale_mismatch)
    else $fatal(1,"MP_SCALE_DIAGNOSTIC");
  a_fp16_scale_diagnostic: assert property (@(posedge clk) disable iff(!rst_n)
    take && (active ? active_mode : mode)==FP16 &&
    (a_block[135:128]!=0 || b_block[135:128]!=0) |=> err_protocol)
    else $fatal(1,"MP_FP16_SCALE_DIAGNOSTIC");
endmodule
