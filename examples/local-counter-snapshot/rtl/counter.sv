module counter #(parameter MUTATION=0,WAIT_CYCLES=0)(input wire clk,rst_n,psel,penable,pwrite,input wire[7:0]paddr,input wire[31:0]pwdata,output wire pready,pslverr,irq,output reg[31:0]prdata,output reg[63:0]count,output reg pending,snapshot_valid);
 reg[31:0]load_low,compare_low,snapshot_high;reg[63:0]compare_value;reg enabled,irq_enable;integer remaining;
 wire mapped=paddr==0 || paddr==4 || paddr==8 || paddr==12 || paddr==16 || paddr==20 || paddr==24 || paddr==28;
 wire bad=!mapped || (pwrite && (paddr==0 || paddr==4));wire done=pready && !bad;
 wire match=enabled && count+64'd1==compare_value;
 assign pready=rst_n && psel && penable && remaining==0;assign pslverr=pready && bad;assign irq=rst_n && pending && irq_enable;
 always @*begin prdata=0;case(paddr)
 0:prdata=count[31:0];4:prdata=snapshot_valid && MUTATION!=1 ? snapshot_high:count[63:32];
 16:prdata=compare_value[31:0];20:prdata=compare_value[63:32];24:prdata={30'b0,irq_enable,enabled};28:prdata=pending;
 default:;endcase end
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin count<=0;pending<=0;snapshot_valid<=0;load_low<=0;compare_low<=0;snapshot_high<=0;compare_value<=0;enabled<=0;irq_enable<=0;remaining<=0;end
 else begin
 if(enabled)count<=MUTATION==2 ? {count[63:32],count[31:0]+32'd1}:count+64'd1;
 if(psel && !penable)remaining<=WAIT_CYCLES;else if(psel && penable && remaining>0)remaining<=remaining-1;
 if(done)begin
 if(pwrite)case(paddr)
 8:begin load_low<=pwdata;if(MUTATION==4)count[31:0]<=pwdata;end
 12:begin count<={pwdata,load_low};snapshot_valid<=0;end
 16:compare_low<=pwdata;20:compare_value<={pwdata,compare_low};24:begin enabled<=pwdata[0];irq_enable<=pwdata[1];end
 28:if(pwdata[0])pending<=0;default:;endcase
 else case(paddr)
 0:begin snapshot_high<=count[63:32];snapshot_valid<=1;end
 4:snapshot_valid<=0;default:;endcase
 end
 if(match && !(done && pwrite && paddr==12))pending<=1;
 if(MUTATION==3 && done && pwrite && paddr==28 && pwdata[0])pending<=0;
 end end endmodule
