// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
`timescale 1ns/1ps
module sv32_tlb #(parameter integer ENTRIES=2,MUTATION=0) (
    input wire clk,rst_n,req_valid,bare,user_mode,sum_enable,mxr,
    input wire [31:0] virtual_address,
    input wire [21:0] root_ppn,
    input wire [8:0] asid,
    input wire [1:0] kind,
    output wire req_ready,hit,mem_valid,
    output wire [33:0] mem_address,
    input wire mem_ready,mem_error,
    input wire [31:0] mem_data,
    output reg resp_valid,
    input wire resp_ready,
    output reg [33:0] physical_address,
    output reg [1:0] fault,
    input wire fence_valid,fence_address_valid,fence_asid_valid,
    input wire [31:0] fence_address,
    input wire [8:0] fence_asid,
    output wire fence_ready
);
    localparam integer IW=$clog2(ENTRIES);
    wire unused_page_offset=^fence_address[11:0];
    reg [1:0] state;
    reg [ENTRIES-1:0] valids,big_page,global_entry;
    reg [19:0] vpn[0:ENTRIES-1];reg [21:0] ppn[0:ENTRIES-1];
    reg [8:0] owner[0:ENTRIES-1];reg [7:0] flags[0:ENTRIES-1];
    reg [IW-1:0] victim;
    reg [31:0] saved_va;reg [21:0] saved_root;reg [8:0] saved_asid;
    reg [1:0] saved_kind;reg saved_user,saved_sum,saved_mxr;
    reg found,permission;reg [IW-1:0] selected;integer i,j;
    always @* begin
        found=0;selected=0;permission=0;
        for(i=0;i<ENTRIES;i=i+1)begin
            if(!found && valids[i] && (global_entry[i] || owner[i]==asid || MUTATION==1) &&
               ((big_page[i] || MUTATION==2) ? vpn[i][19:10]==virtual_address[31:22] : vpn[i]==virtual_address[31:12]))begin
                found=1;selected=IW'(i);
            end
        end
        permission=((user_mode && flags[selected][4]) || (!user_mode && (!flags[selected][4] || (sum_enable && kind!=2)))) &&
            ((kind==0 && (flags[selected][1] || (mxr && flags[selected][3]))) || (kind==1 && flags[selected][2]) || (kind==2 && flags[selected][3])) &&
            flags[selected][6] && (kind!=1 || flags[selected][7]);
    end
    assign fence_ready=rst_n && state==0 && !resp_valid;
    assign req_ready=fence_ready && !fence_valid;
    assign hit=req_valid && req_ready && !bare && found;
    wire w_ready,w_valid,w_large,w_global;wire [7:0] w_flags;
    wire [33:0] w_pa;wire [1:0] w_fault;
    sv32_walk walker(.clk(clk),.rst_n(rst_n),.req_valid(state==1),.bare(1'b0),.user_mode(saved_user),
        .sum_enable(saved_sum),.mxr(saved_mxr),.virtual_address(saved_va),.root_ppn(saved_root),.kind(saved_kind),
        .req_ready(w_ready),.mem_valid(mem_valid),.mem_address(mem_address),.mem_ready(mem_ready),.mem_error(mem_error),.mem_data(mem_data),
        .resp_valid(w_valid),.resp_ready(state==2),.physical_address(w_pa),.fault(w_fault),
        .leaf_flags(w_flags),.large_page(w_large),.global_mapping(w_global));
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=0;valids<=0;big_page<=0;global_entry<=0;victim<=0;resp_valid<=0;physical_address<=0;fault<=0;
            saved_va<=0;saved_root<=0;saved_asid<=0;saved_kind<=0;saved_user<=0;saved_sum<=0;saved_mxr<=0;
            for(j=0;j<ENTRIES;j=j+1)begin vpn[j]<=0;ppn[j]<=0;owner[j]<=0;flags[j]<=0;end
        end else begin
            if(resp_valid && resp_ready)resp_valid<=0;
            if(fence_valid && fence_ready)begin
                for(j=0;j<ENTRIES;j=j+1)begin
                    if((!fence_asid_valid || (!global_entry[j] && owner[j]==fence_asid)) &&
                       (!fence_address_valid || ((big_page[j] && MUTATION!=3) ? vpn[j][19:10]==fence_address[31:22] : vpn[j]==fence_address[31:12])))valids[j]<=0;
                end
            end
            if(req_valid && req_ready)begin
                physical_address<=0;fault<=0;
                if(bare)begin physical_address<={2'b0,virtual_address};resp_valid<=1;end
                else if(found)begin
                    resp_valid<=1;
                    if(permission || MUTATION==4)physical_address<=big_page[selected] ? {ppn[selected][21:10],virtual_address[21:0]} : {ppn[selected],virtual_address[11:0]};
                    else fault<=1;
                end else begin
                    saved_va<=virtual_address;saved_root<=root_ppn;saved_asid<=asid;saved_kind<=kind;
                    saved_user<=user_mode;saved_sum<=sum_enable;saved_mxr<=mxr;state<=1;
                end
            end
            if(state==1 && w_ready)state<=2;
            if(state==2 && w_valid)begin
                state<=0;resp_valid<=1;physical_address<=w_pa;fault<=w_fault;
                if(w_fault==0)begin
                    valids[victim]<=1;vpn[victim]<=saved_va[31:12];ppn[victim]<=w_pa[33:12];owner[victim]<=saved_asid;
                    flags[victim]<=w_flags;big_page[victim]<=w_large;global_entry[victim]<=w_global;
                    victim<=victim==IW'(ENTRIES-1) ? 0 : victim+1'b1;
                end
            end
        end
    end
endmodule
