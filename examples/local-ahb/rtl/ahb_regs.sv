// Teaching AHB-Lite register bank, little-endian 32-bit data bus.
module ahb_regs #(parameter WAIT_CYCLES=0,MUTATION=0)(
    input wire hclk,hresetn,hsel,hready,hwrite,
    input wire [1:0] htrans,
    input wire [2:0] hsize,hburst,
    input wire [9:0] haddr,
    input wire [31:0] hwdata,
    output reg hreadyout,hresp,
    output reg [31:0] hrdata
);
    reg [31:0] registers[0:3];
    reg active,data_write,data_bad,error_second;
    reg [9:0] data_address;
    reg [2:0] data_size;
    integer remaining;
    wire address_bad=(hsize>2) || ((haddr & ((1<<hsize)-1))!=0) ||
                     haddr>=20 || (hwrite && haddr>=16);
    wire [3:0] lanes=(4'b1111 >> (4-(1<<data_size))) << data_address[1:0];
    wire [1:0] target_index=MUTATION==1 ? haddr[3:2] : data_address[3:2];
    always @* begin
        hreadyout=1;hresp=0;hrdata=0;
        if(hresetn && active) begin
            if(remaining>0) hreadyout=0;
            else if(data_bad) begin hresp=1;hreadyout=error_second || MUTATION==3;end
            if(!data_bad && !data_write) begin
                hrdata=data_address>=16 ? 32'h4148424c : registers[data_address[3:2]];
                if(MUTATION==4) hrdata=hrdata ^ 32'h00000001;
            end
        end
    end
    always @(posedge hclk or negedge hresetn) begin
        if(!hresetn) begin
            active<=0;data_write<=0;data_bad<=0;error_second<=0;
            data_address<=0;data_size<=0;remaining<=0;
            for(integer i=0;i<4;i=i+1) registers[i]<=0;
        end else begin
            if(active && hreadyout) begin
                active<=0;
                if(data_write && !hresp)
                    for(integer lane=0;lane<4;lane=lane+1)
                        if(lanes[lane] || MUTATION==2)
                            registers[target_index][8*lane+:8]<=hwdata[8*lane+:8];
            end else if(active) begin
                if(remaining>0) remaining<=remaining-1;
                else if(data_bad) error_second<=1;
            end
            if(hready && hsel && htrans[1]) begin
                active<=1;data_address<=haddr;data_size<=hsize;data_write<=hwrite;
                data_bad<=address_bad;remaining<=WAIT_CYCLES;error_second<=0;
            end
        end
    end
endmodule
