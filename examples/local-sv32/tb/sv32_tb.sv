`timescale 1ns/1ps
module sv32_tb;
    parameter WAIT_CYCLES=0,MUTATION=0;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,req_valid=0,bare=0,user_mode=0,sum_enable=0,mxr=0,mem_ready=0,mem_error=0,resp_ready=0;
    reg [31:0] virtual_address=0,mem_data=0;reg [21:0] root_ppn=0;reg [1:0] kind=0;
    wire req_ready,mem_valid,resp_valid;wire [33:0] mem_address,physical_address;wire [1:0] fault;
    wire [7:0] leaf_flags;wire large_page,global_mapping;
    sv32_walk #(.MUTATION(MUTATION)) dut(.*);
    integer fd,n,checks=0,level=1;reg [63:0] v[0:21];string vectors,wave;
    reg [31:0] last_pte=0;reg saved_bare=0,saved_user=0,saved_sum=0,saved_mxr=0,pending=0;reg [1:0] saved_kind=0;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
        $dumpfile(wave);$dumpvars(0,sv32_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],v[16],v[17],v[18],v[19],v[20],v[21]);
            if(n!=22)$fatal(1,"bad row");
            rst_n=v[0][0];req_valid=v[1][0];bare=v[2][0];user_mode=v[3][0];sum_enable=v[4][0];mxr=v[5][0];
            virtual_address=v[6][31:0];root_ppn=v[7][21:0];kind=v[8][1:0];resp_ready=v[9][0];mem_ready=v[10][0];mem_data=v[11][31:0];mem_error=v[12][0];#1;
            if(req_ready!==v[13][0] || mem_valid!==v[14][0] || resp_valid!==v[16][0])fail("VM_HANDSHAKE");
            if(mem_valid && mem_address!==v[15][33:0])fail("VM_PTE_ADDRESS");
            if(resp_valid && (physical_address!==v[17][33:0] || fault!==v[18][1:0]))fail("VM_RESULT");
            if(resp_valid && (leaf_flags!==v[19][7:0] || large_page!==v[20][0] || global_mapping!==v[21][0]))fail("VM_METADATA");
            if(!rst_n)begin if(pending)$display("COVER reset/pending");pending=0;end
            if(req_ready && req_valid)begin
                pending=1;saved_bare=bare;saved_user=user_mode;saved_sum=sum_enable;saved_mxr=mxr;saved_kind=kind;level=1;last_pte=0;
            end
            if(mem_valid && !mem_ready)$display("COVER memory/wait");
            if(mem_valid && mem_ready)begin
                last_pte=mem_data;
                if(mem_error)$display("COVER fault/pte-access");
                else if(mem_data[0] && !mem_data[1] && !mem_data[2] && !mem_data[3])begin
                    if((mem_data&32'hd0)!=0)$display("COVER deny/nonleaf-reserved");
                    else if(level==0)$display("COVER deny/exhausted-level");
                    else level=0;
                end
            end
            if(resp_valid)begin
                if(!resp_ready)$display("COVER response/hold");
                if(fault==0)begin
                    if(saved_bare)$display("COVER mode/bare");
                    else begin
                        if(level==1)$display("COVER page/4m");else $display("COVER page/4k");
                        if(saved_mxr && saved_kind==0 && !last_pte[1] && last_pte[3])$display("COVER permission/mxr");
                        if(!saved_user && last_pte[4] && saved_sum)$display("COVER permission/sum");
                    end
                end else if(fault==1)begin
                    if(!last_pte[0] || (!last_pte[1] && last_pte[2]))$display("COVER deny/invalid-pte");
                    if(last_pte[1] || last_pte[3])begin
                        if(!last_pte[6])$display("COVER deny/accessed");
                        if(saved_kind==1 && !last_pte[7])$display("COVER deny/dirty");
                        if(saved_user && !last_pte[4])$display("COVER deny/user");
                        if(!saved_user && last_pte[4] && saved_kind==2)$display("COVER deny/supervisor-execute-user");
                        if(level==1 && last_pte[19:10]!=0)$display("COVER deny/superpage-alignment");
                    end
                end
                if(resp_ready)pending=0;
            end
            @(posedge clk);#1;checks=checks+1;@(negedge clk);
        end
        $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
