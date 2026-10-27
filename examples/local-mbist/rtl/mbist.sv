// Classical bit-cell March C-: w0; up(r0,w1); up(r1,w0); down(r0,w1); down(r1,w0); r0.
module mbist #(parameter MUTATION=0,DEPTH=8)(input wire clk,rst_n,start,output reg busy,done,failed,output reg[$clog2(DEPTH)-1:0]fail_addr,output wire req_valid,input wire req_ready,output wire req_write,req_data,output reg[$clog2(DEPTH)-1:0]req_addr,input wire read_data);
 reg[2:0]phase;reg second;
 assign req_valid=rst_n && busy;
 assign req_write=(phase==0 || (phase!=5 && second));
 assign req_data=(phase==1 || phase==3) ^ (MUTATION==3);
 wire expected=phase==2 || phase==4;
 wire element_done=phase==0 || phase==5 || second;
 wire last_addr=(phase==3 || phase==4) ? req_addr==0:req_addr==DEPTH-1;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin busy<=0;done<=0;failed<=0;fail_addr<=0;req_addr<=0;phase<=0;second<=0;end
 else begin
 if(start && !busy)begin busy<=1;done<=0;failed<=0;fail_addr<=0;req_addr<=0;phase<=0;second<=0;end
 else if(req_valid && req_ready)begin
 if(!req_write && read_data!=expected && !failed && MUTATION!=1)begin failed<=1;fail_addr<=req_addr ^ (MUTATION==2 ? 1:0);end
 if(MUTATION==4 && phase==4 && last_addr && second)begin busy<=0;done<=1;end
 else if(element_done)begin
 second<=0;
 if(last_addr)begin
 if(phase==5)begin busy<=0;done<=1;end
 else begin phase<=phase+1'b1;req_addr<=phase==2 || phase==3 ? DEPTH-1:0;end
 end else req_addr<=(phase==3 || phase==4) ? req_addr-1'b1:req_addr+1'b1;
 end else second<=1;
 end end end endmodule
