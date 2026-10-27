// Four sources, one target. Claim selects eligible pending independently of threshold.
module priority_irq #(parameter MUTATION=0,LEVEL=1,WAIT_CYCLES=1)(
 input wire clk,rst_n,psel,penable,pwrite,input wire [7:0] paddr,input wire [31:0] pwdata,
 input wire [3:0] sources,output wire pready,pslverr,irq,output reg [31:0] prdata,
 output reg [3:0] pending,in_service
);
 reg [3:0] enables,previous;reg [1:0] threshold,priorities[0:3];integer remaining,winner,best;
 wire [3:0] arrived=LEVEL ? sources:sources & ~previous;
 wire priority_addr=paddr>=32 && paddr<=44 && paddr[1:0]==0;
 wire mapped=paddr==0 || paddr==4 || paddr==8 || paddr==12 || paddr==16 || priority_addr;
 wire complete=paddr==16 && pwrite;
 wire bad=!mapped || (pwrite && (paddr==8 || paddr==12)) ||
  (complete && (pwdata<1 || pwdata>4 || !in_service[(pwdata-1)&3]));
 always @*begin
 winner=0;best=0;
 for(integer i=0;i<4;i=i+1)if(pending[i] && enables[i] &&
  (MUTATION==1 ? priorities[i]>=best && priorities[i]!=0:priorities[i]>best))begin winner=i+1;best=priorities[i];end
 prdata=0;
 case(paddr)
 0:prdata={28'b0,enables};4:prdata={30'b0,threshold};8:prdata={28'b0,pending};12:prdata={28'b0,in_service};16:prdata=winner;
 default:if(priority_addr)prdata={30'b0,priorities[(paddr-32)/4]};
 endcase
 end
 assign irq=rst_n && winner!=0 && (MUTATION==2 ? best>=threshold:best>threshold);
 assign pready=rst_n && psel && penable && remaining==0;
 assign pslverr=pready && bad;
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin enables<=0;previous<=0;threshold<=0;pending<=0;in_service<=0;remaining<=0;for(integer i=0;i<4;i=i+1)priorities[i]<=0;end
 else begin
 previous<=sources;
 for(integer i=0;i<4;i=i+1)if(arrived[i] && !in_service[i])pending[i]<=1;
 if(psel && !penable)remaining<=WAIT_CYCLES;else if(psel && penable && remaining>0)remaining<=remaining-1;
 if(pready && !bad)begin
 if(pwrite)case(paddr)
 0:enables<=pwdata[3:0];4:threshold<=pwdata[1:0];16:in_service[(pwdata-1)&3]<=0;
 default:if(priority_addr)priorities[(paddr-32)/4]<=pwdata[1:0];
 endcase
 else if(paddr==16 && winner!=0)begin
 pending[winner-1]<=0;if(MUTATION!=3)in_service[winner-1]<=1;
 end
 end
 if(MUTATION==4)pending<=pending & enables;
 end end
endmodule
