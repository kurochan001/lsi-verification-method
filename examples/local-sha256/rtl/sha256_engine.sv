// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Bounded byte-message SHA-256 teaching core. See README for its interface contract.
module sha256_engine #(parameter ROUNDS=1, MUTATION=0)(
 input wire clk,rst_n,cmd_valid, input wire [6:0] length,
 output wire cmd_ready, input wire byte_valid, input wire [7:0] byte_data,
 output wire byte_ready, output reg digest_valid, input wire digest_ready,
 output reg [255:0] digest, output reg error
);
 localparam IDLE=0, LOAD=1, PAD=2, INIT=3, COMPRESS=4;
 reg [2:0] state;
 reg [1023:0] message;
 reg [511:0] block_data;
 reg [6:0] size,index;
 reg second,two_blocks;
 integer round_index;
 reg [31:0] hash[0:7],work[0:7],next_work[0:7],schedule[0:63];
 reg [31:0] t1,t2;
 integer i,j;
 function automatic [31:0] rotr(input [31:0] x,input integer n);
  rotr=(x>>n)|(x<<(32-n));
 endfunction
 function automatic [31:0] initial_hash(input integer n);
  begin case(n)
   0: initial_hash=32'h6a09e667;
   1: initial_hash=32'hbb67ae85;
   2: initial_hash=32'h3c6ef372;
   3: initial_hash=32'ha54ff53a;
   4: initial_hash=32'h510e527f;
   5: initial_hash=32'h9b05688c;
   6: initial_hash=32'h1f83d9ab;
   7: initial_hash=32'h5be0cd19;
   default:initial_hash=0;
  endcase end
 endfunction
 function automatic [31:0] k(input integer n);
  begin case(n)
   0: k=32'h428a2f98;
   1: k=32'h71374491;
   2: k=32'hb5c0fbcf;
   3: k=32'he9b5dba5;
   4: k=32'h3956c25b;
   5: k=32'h59f111f1;
   6: k=32'h923f82a4;
   7: k=32'hab1c5ed5;
   8: k=32'hd807aa98;
   9: k=32'h12835b01;
   10: k=32'h243185be;
   11: k=32'h550c7dc3;
   12: k=32'h72be5d74;
   13: k=32'h80deb1fe;
   14: k=32'h9bdc06a7;
   15: k=32'hc19bf174;
   16: k=32'he49b69c1;
   17: k=32'hefbe4786;
   18: k=32'h0fc19dc6;
   19: k=32'h240ca1cc;
   20: k=32'h2de92c6f;
   21: k=32'h4a7484aa;
   22: k=32'h5cb0a9dc;
   23: k=32'h76f988da;
   24: k=32'h983e5152;
   25: k=32'ha831c66d;
   26: k=32'hb00327c8;
   27: k=32'hbf597fc7;
   28: k=32'hc6e00bf3;
   29: k=32'hd5a79147;
   30: k=32'h06ca6351;
   31: k=32'h14292967;
   32: k=32'h27b70a85;
   33: k=32'h2e1b2138;
   34: k=32'h4d2c6dfc;
   35: k=32'h53380d13;
   36: k=32'h650a7354;
   37: k=32'h766a0abb;
   38: k=32'h81c2c92e;
   39: k=32'h92722c85;
   40: k=32'ha2bfe8a1;
   41: k=32'ha81a664b;
   42: k=32'hc24b8b70;
   43: k=32'hc76c51a3;
   44: k=32'hd192e819;
   45: k=32'hd6990624;
   46: k=32'hf40e3585;
   47: k=32'h106aa070;
   48: k=32'h19a4c116;
   49: k=32'h1e376c08;
   50: k=32'h2748774c;
   51: k=32'h34b0bcb5;
   52: k=32'h391c0cb3;
   53: k=32'h4ed8aa4a;
   54: k=32'h5b9cca4f;
   55: k=32'h682e6ff3;
   56: k=32'h748f82ee;
   57: k=32'h78a5636f;
   58: k=32'h84c87814;
   59: k=32'h8cc70208;
   60: k=32'h90befffa;
   61: k=32'ha4506ceb;
   62: k=32'hbef9a3f7;
   63: k=32'hc67178f2;
   default:k=0;
  endcase end
 endfunction
 assign cmd_ready=rst_n && state==IDLE && !digest_valid;
 assign byte_ready=rst_n && state==LOAD;
 always @* begin
  for(integer q=0;q<16;q=q+1) schedule[q]=block_data[511-q*32-:32];
  for(integer q=16;q<64;q=q+1)
   schedule[q]=schedule[q-16]+(rotr(schedule[q-15],7)^rotr(schedule[q-15],18)^(schedule[q-15]>>3))+
               schedule[q-7]+(rotr(schedule[q-2],17)^rotr(schedule[q-2],19)^(schedule[q-2]>>10));
  for(integer q=0;q<8;q=q+1)next_work[q]=work[q];
  t1=0;t2=0;
  for(integer q=0;q<ROUNDS;q=q+1)begin
   t1=next_work[7]+(rotr(next_work[4],6)^rotr(next_work[4],11)^rotr(next_work[4],25))+
      ((next_work[4]&next_work[5])^(~next_work[4]&next_work[6]))+
      k(round_index+q)+schedule[(round_index+q)%64];
   if(MUTATION==1 && round_index+q==0)t1=t1+1;
   t2=(rotr(next_work[0],2)^rotr(next_work[0],13)^rotr(next_work[0],22))+
      ((next_work[0]&next_work[1])^(next_work[0]&next_work[2])^(next_work[1]&next_work[2]));
   next_work[7]=next_work[6];next_work[6]=next_work[5];next_work[5]=next_work[4];
   next_work[4]=next_work[3]+t1;next_work[3]=next_work[2];next_work[2]=next_work[1];
   next_work[1]=next_work[0];next_work[0]=t1+t2;
  end
 end
 always @(posedge clk)begin
  if(!rst_n)begin
   state<=IDLE;message<=0;block_data<=0;size<=0;index<=0;second<=0;two_blocks<=0;
   round_index<=0;digest_valid<=0;digest<=0;error<=0;
   for(i=0;i<8;i=i+1)begin hash[i]<=0;work[i]<=0;end
  end else begin
   if(digest_valid && digest_ready)digest_valid<=0;
   if(MUTATION==4 && digest_valid && !digest_ready)digest<=digest^256'd1;
   case(state)
    IDLE:if(cmd_valid && cmd_ready)begin
     size<=length;index<=0;message<=0;second<=0;two_blocks<=length>55;error<=length>119;
     for(i=0;i<8;i=i+1)hash[i]<=initial_hash(i);
     if(length>119)begin digest<=0;digest_valid<=1;end
     else if(length==0)state<=PAD;
     else state<=LOAD;
    end
    LOAD:if(byte_valid)begin
     message[1023-int'(index)*8-:8]<=byte_data;index<=index+1;
     if(index+1==size)state<=PAD;
    end
    PAD:begin
     message[1023-int'(size)*8-:8]<=8'h80;
     if(two_blocks)begin
      message[63:0]<=64'(size)*8;
      if(MUTATION==2)message[63:0]<={8'(size*8),56'd0};
     end else begin
      message[575:512]<=64'(size)*8;
      if(MUTATION==2)message[575:512]<={8'(size*8),56'd0};
     end
     state<=INIT;
    end
    INIT:begin
     block_data<=second?message[511:0]:message[1023:512];round_index<=0;
     for(i=0;i<8;i=i+1)work[i]<=(MUTATION==3 && second)?initial_hash(i):hash[i];
     state<=COMPRESS;
    end
    COMPRESS:begin
     for(i=0;i<8;i=i+1)work[i]<=next_work[i];
     if(round_index==64-ROUNDS)begin
      for(j=0;j<8;j=j+1)hash[j]<=hash[j]+next_work[j];
      if(two_blocks && !second)begin second<=1;state<=INIT;end
      else begin
       for(j=0;j<8;j=j+1)digest[255-j*32-:32]<=hash[j]+next_work[j];
       digest_valid<=1;state<=IDLE;
      end
     end else round_index<=round_index+ROUNDS;
    end
    default:state<=IDLE;
   endcase
  end
 end
endmodule
