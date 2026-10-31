// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module scan_logic #(
    parameter integer REVERSE=0,MUTATION=0
) (
    input wire clk,rst_n,scan_enable,scan_in,
    input wire [1:0] primary,
    input wire fault_enable,fault_value,
    input wire [2:0] fault_site,
    output reg [3:0] q,
    output wire scan_out
);
    function automatic inject(input value,input integer site, input enabled, input [2:0] selected, input stuck);
        inject=(enabled && int'(selected)==site && !(MUTATION==4 && site==3)) ? stuck : value;
    endfunction
    wire n0=inject(q[0]&primary[0],0,fault_enable,fault_site,fault_value);
    wire n1=inject(q[1]|primary[1],1,fault_enable,fault_site,fault_value);
    wire n2=inject(n0^n1,2,fault_enable,fault_site,fault_value);
    wire n3=inject(q[2]&~q[3],3,fault_enable,fault_site,fault_value);
    wire n4=inject(n2|n3,4,fault_enable,fault_site,fault_value);
    wire n5=inject(n4&1'b0,5,fault_enable,fault_site,fault_value); // n5 stuck-at-0 is deliberately redundant.
    wire n6=inject(q[0]^q[2]^primary[1],6,fault_enable,fault_site,fault_value);
    wire [3:0] next_q={n5|(q[1]&primary[0]),n6,n4,n2};
    assign scan_out=(REVERSE!=0) ? q[0] : q[3];
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)q<=0;
        else if(scan_enable && MUTATION!=2)begin
            if((REVERSE!=0) ^ (MUTATION==1))q<={scan_in,q[3:1]};
            else q<={q[2:0],scan_in};
        end else if(MUTATION!=3)q<=next_q;
    end
endmodule
