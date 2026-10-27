module crc #(parameter MUTATION=0,INIT=0)(input wire clk,rst_n,s_valid,input wire[31:0]s_data,input wire[3:0]s_keep,input wire s_last,check_enable,input wire[7:0]expected_crc,output wire s_ready,output reg m_valid,input wire m_ready,output reg[7:0]m_crc,output reg m_error);
 reg[7:0]state;reg[7:0]next_crc;reg[7:0]byte_value;
 always @*begin
 next_crc=state;
 for(integer lane=0;lane<4;lane=lane+1)if(s_keep[lane] || MUTATION==2)begin
 byte_value=s_data[8*lane+:8];next_crc=next_crc^byte_value;
 for(integer bitno=0;bitno<8;bitno=bitno+1)next_crc=next_crc[7] ? (next_crc<<1)^(MUTATION==1 ? 8'h09:8'h07):next_crc<<1;
 end end
 assign s_ready=rst_n && !m_valid;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin state<=INIT;m_valid<=0;m_crc<=0;m_error<=0;end
 else begin
 if(m_valid && m_ready)m_valid<=0;
 if(s_valid && s_ready)begin
 if(s_last)begin m_valid<=1;m_crc<=next_crc;m_error<=(check_enable && next_crc!=expected_crc)^(MUTATION==4);state<=MUTATION==3 ? next_crc:INIT;end
 else state<=next_crc;
 end end end endmodule
