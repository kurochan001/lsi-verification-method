// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module pmp #(
    parameter integer AW=16, MUTATION=0
) (
    input wire clk, rst_n, cfg_we, addr_we,
    input wire [1:0] index,
    input wire [31:0] wdata,
    input wire [AW-1:0] address,
    input wire [1:0] size_log2, kind, // kind: read=0, write=1, execute=2
    input wire machine,
    output reg allow,
    output reg [2:0] matched,
    output wire [31:0] configs,
    output wire [4*(AW-2)-1:0] addresses
);
    reg [7:0] cfg[0:3];
    reg [AW-3:0] pa[0:3];
    wire unused_wdata = ^wdata[31:AW-2]; // Unimplemented physical address bits.
    genvar g;
    generate for(g=0;g<4;g=g+1) begin: expose
        assign configs[8*g+:8]=cfg[g];
        assign addresses[(AW-2)*g+:AW-2]=pa[g];
    end endgenerate
    wire lower_locked = (index<3) && cfg[index+1][7] && cfg[index+1][4:3]==1;
    integer r;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            for(r=0;r<4;r=r+1) begin cfg[r]<=0;pa[r]<=0;end
        end else begin
            if(cfg_we && !cfg[index][7]) begin
                // WARL choice: reserved R=0,W=1 is read back as R=0,W=0.
                cfg[index]<={wdata[7],2'b00,wdata[4:2],wdata[1]&wdata[0],wdata[0]};
            end
            if(addr_we && !cfg[index][7] && (MUTATION==4 || !lower_locked))
                pa[index]<=wdata[AW-3:0];
        end
    end
    reg [AW+1:0] lo,hi,span,start_addr,end_addr,mask;
    reg found,ones,full,permission;
    integer i,b;
    always @* begin
        start_addr={{2{1'b0}},address};
        end_addr=start_addr+((AW+2)'(1)<<size_log2);
        allow=machine;matched=4;found=0;
        lo=0;hi=0;span=0;mask=0;ones=0;full=0;permission=0;
        for(i=0;i<4;i=i+1) begin
            lo=0;hi=0;span=0;mask=0;ones=1;
            case(cfg[i][4:3])
                1: begin
                    if(i>0)lo={{4{1'b0}},pa[i-1]}<<2;
                    hi={{4{1'b0}},pa[i]}<<2;
                end
                2: begin lo={{4{1'b0}},pa[i]}<<2;hi=lo+4;end
                3: begin
                    // NAPOT size is 8 * 2^(number of trailing ones).
                    span=8;mask=1;
                    for(b=0;b<AW-2;b=b+1) begin
                        if(ones && pa[i][b]) begin span=span<<1;mask=(mask<<1)|1;end
                        else ones=0;
                    end
                    lo=({{4{1'b0}},pa[i]} & ~mask)<<2;hi=lo+span;
                end
                default: begin end
            endcase
            if(cfg[i][4:3]!=0 && hi>lo && start_addr<hi && end_addr>lo && (!found || MUTATION==1)) begin
                found=1;matched=3'(i);
                full=start_addr>=lo && end_addr<=hi;
                permission=(kind==0 && cfg[i][0]) || (kind==1 && cfg[i][1]) || (kind==2 && cfg[i][2]);
                if(machine && (!cfg[i][7] || MUTATION==3))permission=1;
                allow=(full || MUTATION==2) && permission;
            end
        end
        // The local request interface rejects unsupported sizes/kinds and PA wrap.
        if(size_log2==3 || kind==3 || end_addr>((AW+2)'(1)<<AW))allow=0;
    end
endmodule
