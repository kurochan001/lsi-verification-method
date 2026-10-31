`timescale 1ns/1ps
module tlb_tb;
    parameter ENTRIES=2,MUTATION=0;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,req_valid=0,bare=0,user_mode=0,sum_enable=0,mxr=0,mem_ready=0,mem_error=0,resp_ready=0;
    reg [31:0] virtual_address=0,mem_data=0,fence_address=0;reg [21:0] root_ppn=0;
    reg [8:0] asid=0,fence_asid=0;reg [1:0] kind=0;
    reg fence_valid=0,fence_address_valid=0,fence_asid_valid=0;
    wire req_ready,hit,mem_valid,resp_valid,fence_ready;wire [33:0] mem_address,physical_address;wire [1:0] fault;
    sv32_tlb #(.ENTRIES(ENTRIES),.MUTATION(MUTATION)) dut(.*);
    integer fd,n,checks=0,j;reg [63:0] v[0:26];string vectors,wave;
    reg pending=0,saved_hit=0,saved_bare=0,fence_waited=0;reg [31:0] saved_va=0;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
        $dumpfile(wave);$dumpvars(0,tlb_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],v[16],v[17],v[18],v[19],v[20],v[21],v[22],v[23],v[24],v[25],v[26]);if(n!=27)$fatal(1,"bad row");
            rst_n=v[0][0];req_valid=v[1][0];bare=v[2][0];user_mode=v[3][0];sum_enable=v[4][0];mxr=v[5][0];virtual_address=v[6][31:0];root_ppn=v[7][21:0];asid=v[8][8:0];kind=v[9][1:0];
            fence_valid=v[10][0];fence_address_valid=v[11][0];fence_asid_valid=v[12][0];fence_address=v[13][31:0];fence_asid=v[14][8:0];resp_ready=v[15][0];mem_ready=v[16][0];mem_data=v[17][31:0];mem_error=v[18][0];#1;
            if(req_ready!==v[19][0] || hit!==v[20][0] || fence_ready!==v[21][0] || mem_valid!==v[22][0] || resp_valid!==v[24][0])fail("TLB_FLOW");
            if(mem_valid && mem_address!==v[23][33:0])fail("TLB_PTE_ADDRESS");
            if(resp_valid && (physical_address!==v[25][33:0] || fault!==v[26][1:0]))fail("TLB_RESULT");
            if(!rst_n)begin if(pending)$display("COVER reset/pending");pending=0;end
            if(req_valid && req_ready)begin
                pending=1;saved_hit=hit;saved_bare=bare;saved_va=virtual_address;
                if(bare)$display("COVER mode/bare");
                else if(hit)begin
                    if(dut.big_page[dut.selected])$display("COVER hit/4m");else $display("COVER hit/4k");
                    if(dut.global_entry[dut.selected] && dut.owner[dut.selected]!=asid)$display("COVER hit/global-other-asid");
                end else begin $display("COVER lookup/miss");if(asid!=0)$display("COVER lookup/other-asid");end
            end
            if(mem_valid && !mem_ready)$display("COVER walk/wait");
            if(dut.state==2 && dut.w_valid && dut.w_fault==0 && (&dut.valids))$display("COVER replace/full");
            if(fence_valid && !fence_ready)begin $display("COVER fence/pending-drain");fence_waited=1;end
            if(fence_valid && fence_ready)begin
                case({fence_address_valid,fence_asid_valid})
                    0:$display("COVER fence/all");1:$display("COVER fence/asid");2:$display("COVER fence/address");3:$display("COVER fence/both");
                endcase
                if(req_valid)$display("COVER fence/priority");
                if(fence_waited)begin $display("COVER fence/after-drain");fence_waited=0;end
                for(j=0;j<ENTRIES;j=j+1)if(dut.valids[j] && dut.global_entry[j] && fence_asid_valid)$display("COVER fence/preserve-global");
            end
            if(resp_valid)begin
                if(!resp_ready)$display("COVER response/hold");
                if(fault!=0)begin if(saved_hit)$display("COVER permission/hit-deny");else $display("COVER walk/fault");end
                if(saved_hit && saved_va[11:0]!=0 && !saved_bare)$display("COVER hit/offset");
                if(resp_ready)pending=0;
            end
            @(posedge clk);#1;checks=checks+1;@(negedge clk);
        end
        $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
