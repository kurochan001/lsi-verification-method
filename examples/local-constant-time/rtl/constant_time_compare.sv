// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module constant_time_compare #(parameter integer BYTES=2,MUTATION=0) (
    input wire clk,rst_n,start,result_ready,
    input wire [8*BYTES-1:0] secret,guess,
    output wire ready,
    output reg busy,result_valid,match,
    output wire [2:0] public_status
);
    localparam integer IW=$clog2(BYTES);
    reg [IW-1:0] index;
    reg [8*BYTES-1:0] secret_work,guess_work;
    reg equal_so_far;
    wire byte_equal=(MUTATION==4 ? secret[8*index+:8] : secret_work[7:0])==guess_work[7:0];
    assign ready=rst_n && !busy && !result_valid;
    assign public_status={MUTATION==2 ? secret_work[0] : 1'b0,busy,result_valid};
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            busy<=0;result_valid<=0;match<=0;index<=0;secret_work<=0;guess_work<=0;equal_so_far<=1;
        end else begin
            if(result_valid && result_ready)result_valid<=0;
            if(start && ready)begin
                secret_work<=secret;guess_work<=guess;equal_so_far<=1;index<=0;busy<=1;match<=0;
            end
            if(busy)begin
                if(index==IW'(BYTES-1) || (MUTATION==1 && !byte_equal))begin
                    match<=equal_so_far && (MUTATION==3 ? 1'b1 : byte_equal);
                    result_valid<=1;busy<=0;secret_work<=0;guess_work<=0;
                end else begin
                    equal_so_far<=equal_so_far && byte_equal;index<=index+1'b1;
                    secret_work<=secret_work>>8;guess_work<=guess_work>>8;
                end
            end
        end
    end
endmodule
