// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module coherent_pair #(
    parameter integer LATENCY=1, MUTATION=0
) (
    input wire clk,rst_n,req_valid,req_core,req_write,resp_ready,
    input wire [3:0] req_addr,
    input wire [31:0] req_data,
    output wire req_ready,
    output reg resp_valid,resp_core,
    output reg [31:0] resp_data,
    output wire [3:0] states,
    output wire [7:0] tags,
    output wire [63:0] lines
);
    localparam [1:0] I=0,S=1,M=2;
    reg [1:0] state[0:1];reg [3:0] tag[0:1];reg [31:0] data[0:1];
    reg [31:0] memory[0:15];
    reg busy;integer remaining;
    integer j;
    wire c=req_core,o=~req_core;
    wire hit=state[c]!=I && tag[c]==req_addr;
    wire peer=state[o]!=I && tag[o]==req_addr;
    wire [31:0] value=req_write ? req_data :
        hit ? data[c] : (peer && state[o]==M && MUTATION!=2) ? data[o] : memory[req_addr];
    assign states={state[1],state[0]};assign tags={tag[1],tag[0]};assign lines={data[1],data[0]};
    assign req_ready=rst_n && !busy && !resp_valid;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            busy<=0;remaining<=0;resp_valid<=0;resp_core<=0;resp_data<=0;
            for(j=0;j<2;j=j+1)begin state[j]<=I;tag[j]<=0;data[j]<=0;end
            for(j=0;j<16;j=j+1)memory[j]<=0;
        end else begin
            if(resp_valid && resp_ready)resp_valid<=0;
            if(MUTATION==4 && resp_valid && !resp_ready)resp_data<=resp_data^1;
            if(busy)begin
                if(remaining==1)begin busy<=0;resp_valid<=1;remaining<=0;end
                else remaining<=remaining-1;
            end
            if(req_valid && req_ready)begin
                if(!hit && state[c]==M && MUTATION!=3)memory[tag[c]]<=data[c];
                if(req_write)begin
                    if(peer)begin
                        if(state[o]==M)memory[req_addr]<=data[o];
                        if(MUTATION!=1)state[o]<=I;
                    end
                    state[c]<=M;
                end else begin
                    if(!hit)begin
                        if(peer && state[o]==M)begin
                            memory[req_addr]<=data[o];state[o]<=S;
                        end
                        state[c]<=S;
                    end
                end
                tag[c]<=req_addr;data[c]<=value;
                resp_data<=value;resp_core<=req_core;busy<=1;remaining<=LATENCY;
            end
        end
    end
endmodule
