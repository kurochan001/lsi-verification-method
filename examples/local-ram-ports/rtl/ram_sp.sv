// One shared read/write port. Memory contents are not reset.
module ram_sp #(parameter DATA_W=32,DEPTH=16,MUTATION=0)(
    input wire clk,rst_n,en,write,
    input wire [$clog2(DEPTH)-1:0] address,
    input wire [DATA_W-1:0] wdata,input wire [DATA_W/8-1:0] byte_enable,
    output reg [DATA_W-1:0] rdata
);
    reg [DATA_W-1:0] memory[0:DEPTH-1];
    always @(posedge clk) begin
        if (!rst_n) rdata<=0;
        else if (en) begin
            if (write) begin
                for (integer lane=0;lane<DATA_W/8;lane=lane+1)
                    if (byte_enable[lane] || MUTATION==8) memory[address][lane*8+:8]<=wdata[lane*8+:8];
            end else rdata<=memory[address];
        end
    end
endmodule
