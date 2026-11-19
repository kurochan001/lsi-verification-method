module byte_word_ram #(
    parameter integer DATA_W=32, DEPTH=16, AW=$clog2(DEPTH)
)(
    input wire clk, enable, write,
    input wire [AW-1:0] address,
    input wire [DATA_W-1:0] write_data,
    input wire [DATA_W/8-1:0] byte_enable,
    output reg [DATA_W-1:0] read_data
);
    reg [DATA_W-1:0] memory[0:DEPTH-1];
    always @(posedge clk) begin
        if(enable) begin
            if(write) begin
                for(integer b=0;b<DATA_W/8;b=b+1)
                    if(byte_enable[b])memory[address][8*b+:8]<=write_data[8*b+:8];
            end else read_data<=memory[address];
        end
    end
endmodule
