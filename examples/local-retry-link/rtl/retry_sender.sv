// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module retry_sender #(parameter integer TIMEOUT=3,RETRIES=2,MUTATION=0)(
    input wire clk,rst_n,s_valid,wire_ready,ack_valid,done_ready,
    input wire [7:0] s_data,
    input wire [3:0] ack,
    output wire s_ready,wire_valid,
    output wire [16:0] wire_word,
    output reg done_valid,error,failed
);
    localparam integer TW=$clog2(TIMEOUT),RW=$clog2(RETRIES+1);
    reg [1:0] state;reg seq;reg [7:0] payload;
    reg [TW-1:0] age;reg [RW-1:0] retried;
    wire [7:0] check_byte;crc9 encoder(.message({seq,payload}),.crc(check_byte));
    assign wire_word={seq,payload,check_byte};
    assign wire_valid=rst_n && state==1;
    assign s_ready=rst_n && state==0 && !done_valid && !failed;
    wire ack_good=ack_valid && (ack==4'h3 || ack==4'hc) && (ack[3]==seq || MUTATION==4);
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin state<=0;seq<=0;payload<=0;age<=0;retried<=0;done_valid<=0;error<=0;failed<=0;end
        else begin
            if(done_valid && done_ready)done_valid<=0;
            if(s_valid && s_ready)begin payload<=s_data;state<=1;retried<=0;age<=0;error<=0;end
            if(state==1 && wire_ready)begin state<=2;age<=0;end
            if(state==2)begin
                if(ack_good)begin state<=0;done_valid<=1;error<=0;seq<=~seq;end
                else if(age==TW'(TIMEOUT-1))begin
                    age<=0;
                    if(retried<RW'(RETRIES))begin
                        retried<=retried+1'b1;state<=1;
                        if(MUTATION==1)seq<=~seq;
                    end else begin state<=0;done_valid<=1;error<=1;failed<=1;end
                end else age<=age+1'b1;
            end
        end
    end
endmodule
