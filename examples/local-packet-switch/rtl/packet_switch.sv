// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
module packet_switch #(parameter WIDTH=8,MUTATION=0)(
 input wire clk,rst_n,input wire [1:0] s_valid,s_last,s_dest,
 input wire [2*WIDTH-1:0] s_data,output reg [1:0] s_ready,
 output reg [1:0] m_valid,m_last,output reg [2*WIDTH-1:0] m_data,
 input wire [1:0] m_ready
);
 reg [1:0] locked,owner,prefer,in_packet,route;
 integer selected[0:1];
 reg [1:0] destination;
 always @* begin
  destination=(MUTATION==3)?s_dest:((in_packet & route)|(~in_packet & s_dest));
  s_ready=0;m_valid=0;m_last=0;m_data=0;
  for(integer o=0;o<2;o=o+1)begin
   selected[o]=-1;
   if(locked[o] && MUTATION!=1)selected[o]=int'(owner[o]);
   else if(s_valid[0] && destination[0]==1'(o) && s_valid[1] && destination[1]==1'(o))
    selected[o]=(MUTATION==2)?0:int'(prefer[o]);
   else if(s_valid[0] && destination[0]==1'(o))selected[o]=0;
   else if(s_valid[1] && destination[1]==1'(o))selected[o]=1;
   if(rst_n && selected[o]>=0 && s_valid[selected[o]] && destination[selected[o]]==1'(o))begin
    m_valid[o]=1;m_last[o]=s_last[selected[o]];
    if(MUTATION==4)m_last[o]=1;
    m_data[o*WIDTH+:WIDTH]=s_data[selected[o]*WIDTH+:WIDTH];
    s_ready[selected[o]]=m_ready[o];
   end
  end
 end
 always @(posedge clk)begin
  if(!rst_n)begin locked<=0;owner<=0;prefer<=0;in_packet<=0;route<=0;end
  else begin
   for(integer o=0;o<2;o=o+1)begin
    if(m_valid[o])begin
     // Reserve even an unaccepted header so output data stays stable under backpressure.
     locked[o]<=1;owner[o]<=1'(selected[o]);
     if(m_ready[o] && m_last[o])begin locked[o]<=0;prefer[o]<=selected[o]==0;end
    end
   end
   for(integer s=0;s<2;s=s+1)if(s_valid[s] && s_ready[s])begin
    in_packet[s]<=!s_last[s];
    if(!in_packet[s])route[s]<=s_dest[s];
   end
  end
 end
endmodule
