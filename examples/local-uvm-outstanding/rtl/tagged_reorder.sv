`timescale 1ns/1ps
module tagged_reorder #(parameter MUTATION=0)(
 input wire clk,rst_n,release_enable,s_valid,input wire [1:0] s_id,
 input wire [15:0] s_token,input wire [7:0] s_data,output wire s_ready,
 output wire m_valid,input wire m_ready,output wire [1:0] m_id,
 output wire [15:0] m_token,output wire [7:0] m_data
);
 reg [3:0] occupied;reg [1:0] ids[4];reg [15:0] tokens[4];reg [7:0] data[4];reg [2:0] delay_count[4];
 reg held,started;reg [1:0] selected;
 generate if(MUTATION==4)begin:mutation_initial_state
  initial started=0;
 end endgenerate
 integer free_slot,candidate;reg id_busy;
 always @*begin
  free_slot=-1;candidate=-1;id_busy=0;
  for(integer i=0;i<4;i=i+1)begin
   if(!occupied[i] && free_slot<0)free_slot=i;
   if(occupied[i] && ids[i]==s_id)id_busy=1;
   if(occupied[i] && (delay_count[i]==0 || MUTATION==7))candidate=i;
  end
 end
 assign s_ready=rst_n && free_slot>=0 && (!id_busy || MUTATION==5);
 assign m_valid=rst_n && held;
 assign m_id=(MUTATION==6) ? selected:ids[selected];
 assign m_token=tokens[selected]^((MUTATION==2) ? 16'd1:16'd0);
 assign m_data=data[selected]^((MUTATION==1) ? 8'd1:8'd0);
 always @(posedge clk)begin
  if(!rst_n)begin
   held<=0;selected<=0;
   if(MUTATION!=4 || !started)occupied<=0;
  end else begin
   started<=1;
   for(integer i=0;i<4;i=i+1)if(occupied[i] && delay_count[i]!=0)delay_count[i]<=delay_count[i]-3'd1;
   if(held && m_ready)begin held<=0;if(MUTATION!=3)occupied[selected]<=0;end
   if((!held || (MUTATION==8 && !m_ready)) && release_enable && candidate>=0)begin held<=1;selected<=2'(candidate);end
   if(s_valid && s_ready)begin
    occupied[free_slot]<=1;ids[free_slot]<=s_id;tokens[free_slot]<=s_token;
    data[free_slot]<=(s_data<<1)+s_data+{6'b0,s_id};delay_count[free_slot]<=s_data[2:0];
   end
  end
 end
endmodule
