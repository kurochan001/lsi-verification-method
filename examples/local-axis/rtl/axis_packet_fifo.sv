// 32-bit AXI4-Stream packet FIFO, including sparse TKEEP and TLAST.
module axis_packet_fifo #(parameter DEPTH=2,MUTATION=0)(
 input wire clk,rst_n,s_valid,input wire [31:0] s_data,input wire [3:0] s_keep,input wire s_last,
 output wire s_ready,output wire m_valid,output wire [31:0] m_data,output wire [3:0] m_keep,output wire m_last,input wire m_ready
);
 localparam A=$clog2(DEPTH);
 reg [36:0] memory[0:DEPTH-1];reg [A-1:0] head,tail;reg [A:0] count;
 assign s_ready=rst_n && (MUTATION==4 || count<DEPTH || (m_valid && m_ready));
 assign m_valid=rst_n && count!=0;
 assign m_data=memory[head][31:0] ^ (MUTATION==3 ? 32'b1:0);
 assign m_keep=MUTATION==2 ? 4'hf:memory[head][35:32];
 assign m_last=MUTATION==1 ? 1'b0:memory[head][36];
 wire push=s_valid&&s_ready,pop=m_valid&&m_ready;
 always @(posedge clk or negedge rst_n)begin
  if(!rst_n)begin head<=0;tail<=0;count<=0;end
  else begin
   if(push)begin memory[tail]<={s_last,s_keep,s_data};tail<=tail+1'b1;end
   if(pop)head<=head+1'b1;
   case({push,pop})2'b10:count<=count+1'b1;2'b01:count<=count-1'b1;default:;endcase
  end
 end
endmodule
