`timescale 1ns/1ps
module coherence_tb;
    parameter LATENCY=1,MUTATION=0;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,req_valid=0,req_core=0,req_write=0,resp_ready=0;
    reg [3:0] req_addr=0;reg [31:0] req_data=0;
    wire req_ready,resp_valid,resp_core;wire [31:0] resp_data;
    wire [3:0] states;wire [7:0] tags;wire [63:0] lines;
    coherent_pair #(.LATENCY(LATENCY),.MUTATION(MUTATION)) dut(.*);
    integer fd,n,checks=0,c,o,j;reg [511:0] v[0:11];string vectors,wave;
    reg [1:0] state[0:1];reg [3:0] tag[0:1];reg [31:0] data[0:1];reg hit,peer,pending=0;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
        $dumpfile(wave);$dumpvars(0,coherence_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");
        repeat(2)@(negedge clk);
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11]);if(n!=12)$fatal(1,"bad row");
            rst_n=v[0][0];req_valid=v[1][0];req_core=v[2][0];req_write=v[3][0];req_addr=v[4][3:0];req_data=v[5][31:0];resp_ready=v[6][0];#1;
            if(req_ready!==v[7][0] || resp_valid!==v[8][0])fail("CACHE_HANDSHAKE");
            if(resp_valid && (resp_core!==v[9][0] || resp_data!==v[10][31:0]))fail("CACHE_RESPONSE");
            for(j=0;j<2;j=j+1)begin
                state[j]=states[2*j+:2];tag[j]=tags[4*j+:4];data[j]=lines[32*j+:32];
                if(state[j]>2)fail("CACHE_DATA");
                if(state[j]!=0 && data[j]!==v[11][32*tag[j]+:32])fail("CACHE_DATA");
            end
            if(tag[0]==tag[1] && state[0]!=0 && state[1]!=0)begin
                if(state[0]==2 || state[1]==2)fail("CACHE_DATA");
                $display("COVER state/shared-pair");
            end
            if(!rst_n)begin if(pending)$display("COVER reset/pending");pending=0;end
            if(resp_valid && resp_ready)pending=0;
            if(resp_valid && !resp_ready)$display("COVER response/backpressure");
            if(req_ready && req_valid)begin
                pending=1;c=int'(req_core);o=1-c;
                hit=state[c]!=0 && tag[c]==req_addr;peer=state[o]!=0 && tag[o]==req_addr;
                if(c==0)$display("COVER client/zero");else $display("COVER client/one");
                if(!req_write)begin
                    if(hit)$display("COVER read/hit");else $display("COVER read/miss");
                    if(!hit && peer && state[o]==2)$display("COVER read/dirty-forward");
                end else begin
                    if(hit && state[c]==1)$display("COVER write/shared-upgrade");
                    if(hit && state[c]==2)$display("COVER write/modified-hit");
                    if(peer)$display("COVER write/invalidate-peer");
                end
                if(!hit && state[c]==2)$display("COVER eviction/dirty");
            end
            @(posedge clk);#1;checks=checks+1;@(negedge clk);
        end
        $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
