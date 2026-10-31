// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module crc9(input wire [8:0] message,output reg [7:0] crc);
    integer i;reg feedback;
    always @* begin
        crc=0;feedback=0;
        for(i=8;i>=0;i=i-1)begin
            feedback=crc[7]^message[i];crc={crc[6:0],1'b0};
            if(feedback)crc=crc^8'h07;
        end
    end
endmodule
