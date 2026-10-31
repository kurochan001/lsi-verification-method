// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module store_buffer #(parameter integer DEPTH=2,MUTATION=0)(
    input wire clk,rst_n,req_valid,core,drain_valid,drain_core,resp_ready,
    input wire [1:0] op,address,
    input wire [31:0] write_data,
    output wire req_ready,drain_fire,
    output reg resp_valid,resp_core,
    output reg [1:0] resp_op,
    output reg [31:0] resp_data,
    output wire [127:0] visible_memory,
    output wire [2*$clog2(DEPTH+1)-1:0] occupancy
);
    localparam integer CW=$clog2(DEPTH+1),IW=$clog2(DEPTH);
    reg [31:0] memory[0:3];reg [31:0] data[0:1][0:DEPTH-1];reg [1:0] addr[0:1][0:DEPTH-1];
    reg [CW-1:0] count[0:1];
    assign occupancy={count[1],count[0]};
    genvar g;generate for(g=0;g<4;g=g+1)begin: expose
        assign visible_memory[32*g+:32]=memory[g];
    end endgenerate
    assign drain_fire=rst_n && drain_valid && count[drain_core]!=0;
    wire same_drain=drain_fire && drain_core==core;
    wire [CW-1:0] after_count=count[core]-CW'(same_drain);
    wire [IW-1:0] drain_index=MUTATION==3 ? IW'(count[drain_core]-1'b1) : 0;
    wire [31:0] drain_data=data[drain_core][drain_index];
    wire [1:0] drain_address=addr[drain_core][drain_index];
    assign req_ready=rst_n && !resp_valid && op<=2 &&
        (op==1 ? after_count<CW'(DEPTH) : op==2 ? (after_count==0 || MUTATION==2) : 1'b1);
    reg [31:0] loaded;integer i,j,k;
    always @* begin
        loaded=memory[address];
        if(drain_fire && drain_address==address && MUTATION!=4)loaded=drain_data;
        for(i=0;i<DEPTH;i=i+1)begin
            if(i<int'(count[core]) && !(same_drain && i==0) && addr[core][i]==address && MUTATION!=1)loaded=data[core][i];
        end
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            resp_valid<=0;resp_core<=0;resp_op<=0;resp_data<=0;
            for(j=0;j<4;j=j+1)memory[j]<=0;
            for(j=0;j<2;j=j+1)begin
                count[j]<=0;
                for(k=0;k<DEPTH;k=k+1)begin data[j][k]<=0;addr[j][k]<=0;end
            end
        end else begin
            if(resp_valid && resp_ready)resp_valid<=0;
            if(drain_fire)begin
                memory[drain_address]<=drain_data;count[drain_core]<=count[drain_core]-1'b1;
                for(j=0;j<DEPTH-1;j=j+1)begin data[drain_core][j]<=data[drain_core][j+1];addr[drain_core][j]<=addr[drain_core][j+1];end
            end
            if(req_valid && req_ready)begin
                resp_valid<=1;resp_core<=core;resp_op<=op;resp_data<=op==0 ? loaded : op==1 ? write_data : 0;
                if(op==1)begin
                    data[core][IW'(after_count)]<=write_data;addr[core][IW'(after_count)]<=address;count[core]<=after_count+1'b1;
                end
            end
        end
    end
endmodule
