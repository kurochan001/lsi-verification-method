// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module sv32_walk #(parameter integer MUTATION=0) (
    input wire clk,rst_n,req_valid,bare,user_mode,sum_enable,mxr,
    input wire [31:0] virtual_address,
    input wire [21:0] root_ppn,
    input wire [1:0] kind,
    output wire req_ready,mem_valid,
    output reg [33:0] mem_address,
    input wire mem_ready,mem_error,
    input wire [31:0] mem_data,
    output reg resp_valid,
    input wire resp_ready,
    output reg [33:0] physical_address,
    output reg [1:0] fault, // 0: success, 1: page fault, 2: PTE access fault
    output reg [7:0] leaf_flags,
    output reg large_page,global_mapping
);
    reg walking,level_one,saved_user,saved_sum,saved_mxr,path_global;
    reg [21:0] va;reg [1:0] access_kind;
    wire leaf=mem_data[1] || mem_data[3] || (MUTATION==2 && mem_data[2]);
    wire valid_pte=mem_data[0] && (mem_data[1] || !mem_data[2] || MUTATION==2);
    wire privilege_ok=saved_user ? mem_data[4] :
        !mem_data[4] || (saved_sum && (access_kind!=2 || MUTATION==3));
    wire permission_ok=(access_kind==0 && (mem_data[1] || (saved_mxr && mem_data[3]))) ||
        (access_kind==1 && mem_data[2]) || (access_kind==2 && mem_data[3]);
    wire ad_ok=mem_data[6] && (access_kind!=1 || mem_data[7] || MUTATION==4);
    wire aligned=!level_one || mem_data[19:10]==0 || MUTATION==1;
    assign req_ready=rst_n && !walking && !resp_valid;
    assign mem_valid=rst_n && walking;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            walking<=0;level_one<=0;resp_valid<=0;physical_address<=0;fault<=0;mem_address<=0;
            va<=0;access_kind<=0;saved_user<=0;saved_sum<=0;saved_mxr<=0;
            leaf_flags<=0;large_page<=0;global_mapping<=0;path_global<=0;
        end else begin
            if(resp_valid && resp_ready)resp_valid<=0;
            if(req_valid && req_ready)begin
                va<=virtual_address[21:0];access_kind<=kind;saved_user<=user_mode;saved_sum<=sum_enable;saved_mxr<=mxr;
                fault<=0;physical_address<=0;
                leaf_flags<=0;large_page<=0;global_mapping<=0;path_global<=0;
                if(bare)begin resp_valid<=1;physical_address<={2'b00,virtual_address};end
                else begin
                    walking<=1;level_one<=1;
                    mem_address<={root_ppn,12'b0}+{22'b0,virtual_address[31:22],2'b0};
                end
            end
            if(mem_valid && mem_ready)begin
                if(mem_error || !valid_pte || (leaf && (!privilege_ok || !permission_ok || !ad_ok || !aligned)) ||
                   (!leaf && (!level_one || (mem_data & 32'hd0)!=0)))begin
                    walking<=0;resp_valid<=1;physical_address<=0;fault<=mem_error ? 2 : 1;
                end else if(leaf)begin
                    walking<=0;resp_valid<=1;fault<=0;
                    leaf_flags<=mem_data[7:0];large_page<=level_one;global_mapping<=path_global|mem_data[5];
                    physical_address<=level_one ? {mem_data[31:20],va[21:0]} : {mem_data[31:10],va[11:0]};
                end else begin
                    level_one<=0;
                    path_global<=path_global|mem_data[5];
                    mem_address<={mem_data[31:10],12'b0}+{22'b0,va[21:12],2'b0};
                end
            end
        end
    end
endmodule
