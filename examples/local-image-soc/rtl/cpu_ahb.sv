// One aligned word at a time. Address and data phases are distinct AHB-Lite cycles.
module cpu_ahb #(parameter MUTATION=0)(
    input wire clk,rst_n,cpu_valid,cpu_write,
    input wire [31:0] cpu_addr,cpu_wdata,
    output wire cpu_ready,output wire [31:0] cpu_rdata,
    output wire [31:0] haddr,hwdata,output wire [1:0] htrans,
    output wire hwrite,output wire [2:0] hsize,hburst,
    input wire hready,hresp,input wire [31:0] hrdata,
    output reg bus_fault
);
    localparam IDLE=0,ADDRESS=1,DATA=2;
    reg [1:0] state;
    reg [31:0] address,payload;
    reg write_access;
    assign haddr=address ^ (MUTATION==1 ? 32'd4 : 32'd0);
    assign hwdata=payload;assign hwrite=write_access;
    assign hsize=3'd2;assign hburst=3'd0;
    assign htrans=state==ADDRESS ? 2'b10 : 2'b00;
    assign cpu_ready=state==DATA && hready;
    assign cpu_rdata=hrdata;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin state<=IDLE;address<=0;payload<=0;write_access<=0;bus_fault<=0;end
        else case(state)
            IDLE:if(cpu_valid)begin address<=cpu_addr;payload<=cpu_wdata;write_access<=cpu_write;state<=ADDRESS;end
            ADDRESS:if(hready)state<=DATA;
            DATA:if(hready)begin state<=IDLE;if(hresp)bus_fault<=1;end
            default:state<=IDLE;
        endcase
    end
endmodule
