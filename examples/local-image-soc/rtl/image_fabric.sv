// Non-pipelined AHB-Lite fabric: ROM, shared RAM, APB, or two-cycle ERROR.
module image_fabric #(parameter WAIT_CYCLES=0,MUTATION=0)(
    input wire clk,rst_n,input wire [31:0] haddr,hwdata,
    input wire [1:0] htrans,input wire hwrite,input wire [2:0] hsize,hburst,
    output reg hready,hresp,output reg [31:0] hrdata,
    output wire ram_req,ram_write,output wire [31:0] ram_addr,ram_wdata,
    input wire ram_ready,input wire [31:0] ram_rdata,rom_rdata,
    output wire [31:0] rom_addr,
    output wire psel,penable,pwrite,output wire [7:0] paddr,output wire [31:0] pwdata,
    input wire pready,pslverr,input wire [31:0] prdata
);
    localparam IDLE=0,ROM=1,RAM=2,SETUP=3,ACCESS=4,ERROR1=5,ERROR2=6;
    reg [2:0] state;
    reg [31:0] address,error_data;
    reg write_access;
    integer remaining;
    assign ram_req=state==RAM && remaining==0;
    assign ram_write=write_access;assign ram_addr=address;assign ram_wdata=hwdata;
    assign rom_addr=address;
    assign psel=state==SETUP || state==ACCESS;assign penable=state==ACCESS;
    assign pwrite=write_access;assign paddr=address[7:0] ^ (MUTATION==2 ? 8'd4 : 8'd0);assign pwdata=hwdata;
    always @* begin
        hready=state==IDLE;hresp=0;hrdata=0;
        case(state)
            ROM:begin hready=remaining==0;hrdata=rom_rdata;end
            RAM:begin hready=remaining==0 && ram_ready;hrdata=ram_rdata;end
            ACCESS:begin hready=pready && !pslverr;hrdata=prdata;end
            ERROR1:begin hresp=1;hrdata=error_data;end
            ERROR2:begin hready=1;hresp=1;hrdata=error_data;end
            default:;
        endcase
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin state<=IDLE;address<=0;write_access<=0;remaining<=0;error_data<=0;end
        else case(state)
            IDLE:if(htrans==2'b10 || htrans==2'b11)begin
                address<=haddr;write_access<=hwrite;remaining<=WAIT_CYCLES;error_data<=0;
                if(hsize!=2 || hburst!=0 || haddr[1:0]!=0)state<=ERROR1;
                else if(haddr<32'h1000)state<=hwrite ? ERROR1 : ROM;
                else if(haddr<32'h2000)state<=RAM;
                else if(haddr[31:8]==24'h400000)state<=SETUP;
                else state<=ERROR1;
            end
            ROM,RAM:if(remaining!=0)remaining<=remaining-1;else if(hready)state<=IDLE;
            SETUP:state<=ACCESS;
            ACCESS:if(pready)begin
                if(pslverr)begin error_data<=prdata;state<=ERROR1;end
                else state<=IDLE;
            end
            ERROR1:state<=ERROR2;
            ERROR2:state<=IDLE;
            default:state<=IDLE;
        endcase
    end
endmodule
