module sync_dual_clock_ram #(
    parameter integer WIDTH=32, DEPTH=8, READ_LATENCY=1, AW=$clog2(DEPTH)
)(
    input wire wr_clk, wr_enable,
    input wire [AW-1:0] wr_address,
    input wire [WIDTH-1:0] wr_data,
    input wire rd_clk, arst_n, rd_enable,
    input wire [AW-1:0] rd_address,
    output wire rd_valid,
    output wire [WIDTH-1:0] rd_data
);
    reg [WIDTH-1:0] memory[0:DEPTH-1];
    reg [WIDTH-1:0] data_pipe[0:READ_LATENCY-1];
    reg [READ_LATENCY-1:0] valid_pipe;
    always @(posedge wr_clk)if(wr_enable)memory[wr_address]<=wr_data;
    always @(posedge rd_clk)begin
        if(rd_enable)data_pipe[0]<=memory[rd_address];
        for(integer i=1;i<READ_LATENCY;i=i+1)data_pipe[i]<=data_pipe[i-1];
    end
    always @(posedge rd_clk or negedge arst_n)begin
        if(!arst_n)valid_pipe<='0;
        else begin
            valid_pipe[0]<=rd_enable;
            for(integer i=1;i<READ_LATENCY;i=i+1)valid_pipe[i]<=valid_pipe[i-1];
        end
    end
    assign rd_valid=valid_pipe[READ_LATENCY-1];
    assign rd_data=data_pipe[READ_LATENCY-1];
endmodule
