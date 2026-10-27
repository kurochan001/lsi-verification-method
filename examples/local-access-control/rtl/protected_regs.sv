// Teaching APB4 subset: secure privileged configuration, one-way lock until reset.
module protected_regs #(parameter MUTATION=0,WAIT_CYCLES=0)(
 input wire clk,rst_n,psel,penable,pwrite,input wire [7:0] paddr,input wire [31:0] pwdata,
 input wire [2:0] pprot,output wire pready,pslverr,output reg [31:0] prdata,
 output reg [31:0] public_value,secret_value,output reg locked
);
 integer remaining;
 wire config_addr=paddr==8'h10,lock_addr=paddr==8'h14;
 wire mapped=paddr==0 || config_addr || lock_addr;
 // PPROT[0]=privileged, [1]=non-secure, [2]=instruction.
 wire authority=(MUTATION==1 || (pprot[0] && !pprot[1])) && !pprot[2];
 wire denied=!mapped || ((config_addr || lock_addr) && !authority) ||
             (pwrite && config_addr && locked && MUTATION!=2);
 assign pready=rst_n && psel && penable && remaining==0;
 assign pslverr=pready && denied;
 always @* begin
 prdata=0;
 if(!denied || MUTATION==4)case(paddr)
  0:prdata=public_value;8'h10:prdata=secret_value;8'h14:prdata={31'b0,locked};default:;
 endcase
 end
 always @(posedge clk or negedge rst_n)begin
 if(!rst_n)begin remaining<=0;public_value<=0;secret_value<=0;locked<=0;end
 else begin
 if(psel&&!penable)remaining<=WAIT_CYCLES;
 else if(psel&&penable&&remaining>0)remaining<=remaining-1;
 if(pready && pwrite && (!denied || MUTATION==3))begin
  case(paddr)
   0:public_value<=pwdata;8'h10:secret_value<=pwdata;8'h14:locked<=locked | pwdata[0];default:;
  endcase
 end
 end end
endmodule
