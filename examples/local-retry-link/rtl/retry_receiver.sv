// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module retry_receiver #(parameter integer MUTATION=0)(
    input wire clk,rst_n,wire_valid,m_ready,
    input wire [16:0] wire_word,
    output reg m_valid,ack_valid,
    output reg [7:0] m_data,
    output reg [3:0] ack
);
    reg expected_seq;
    wire [7:0] check_byte;crc9 crc_check(.message(wire_word[16:8]),.crc(check_byte));
    wire crc_good=wire_word[7:0]==check_byte || MUTATION==2;
    wire duplicate=wire_word[16]!=expected_seq && MUTATION!=3;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin expected_seq<=0;m_valid<=0;m_data<=0;ack_valid<=0;ack<=0;end
        else begin
            ack_valid<=0;
            if(m_valid && m_ready)m_valid<=0;
            if(wire_valid && crc_good)begin
                if(duplicate || !m_valid || m_ready)begin
                    ack_valid<=1;ack<=wire_word[16] ? 4'hc : 4'h3;
                    if(!duplicate)begin m_valid<=1;m_data<=wire_word[15:8];expected_seq<=~expected_seq;end
                end
            end
        end
    end
endmodule
