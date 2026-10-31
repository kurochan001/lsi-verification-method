`timescale 1ns/1ps
module ordering_tb;
    parameter DEPTH=2,MUTATION=0;
    localparam CW=$clog2(DEPTH+1);
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,req_valid=0,core=0,drain_valid=0,drain_core=0,resp_ready=0;
    reg [1:0] op=0,address=0;reg [31:0] write_data=0;
    wire req_ready,drain_fire,resp_valid,resp_core;wire [1:0] resp_op;wire [31:0] resp_data;
    wire [127:0] visible_memory;wire [2*CW-1:0] occupancy;
    store_buffer #(.DEPTH(DEPTH),.MUTATION(MUTATION)) dut(.*);
    integer fd,n,checks=0,stores=0,commits=0,loads=0,fences=0,r0=-1,r1=-1;
    reg pending=0;reg [127:0] v[0:17];string vectors,wave;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
        $dumpfile(wave);$dumpvars(0,ordering_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");repeat(2)@(negedge clk);
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],v[16],v[17]);if(n!=18)$fatal(1,"bad row");
            rst_n=v[0][0];req_valid=v[1][0];core=v[2][0];op=v[3][1:0];address=v[4][1:0];write_data=v[5][31:0];drain_valid=v[6][0];drain_core=v[7][0];resp_ready=v[8][0];#1;
            if(req_ready!==v[10][0] || drain_fire!==v[11][0] || resp_valid!==v[12][0] || occupancy!==v[17][2*CW-1:0])fail("ORDER_FLOW");
            if(visible_memory!==v[16])fail("ORDER_MEMORY");
            if(resp_valid && (resp_core!==v[13][0] || resp_op!==v[14][1:0] || resp_data!==v[15][31:0]))fail("ORDER_DATA");
            if(!rst_n)begin if(pending)$display("COVER reset/pending-store");pending=0;r0=-1;r1=-1;end
            if(rst_n)begin
                if(resp_valid && !resp_ready)$display("COVER response/hold");
                if(req_valid && !req_ready && !resp_valid)begin
                    if(op==2)$display("COVER fence/waits-for-store");
                    if(op==1)$display("COVER buffer/full-stall");
                end
                if(req_valid && req_ready)begin
                    if(op==1)begin stores=stores+1;pending=1;$display("COVER store/posted");end
                    if(op==2)begin fences=fences+1;$display("COVER fence/completed");end
                    if(op==0)begin
                        loads=loads+1;
                        if(dut.count[core]!=0)$display("COVER load/local-buffer");
                        if(dut.count[~core]!=0)$display("COVER load/remote-buffer");
                        if(drain_fire && drain_core!=core)$display("COVER load/same-cycle-drain");
                    end
                end
                if(drain_fire)begin
                    commits=commits+1;$display("COVER store/visible");
                    if(req_valid && req_ready && op==1 && drain_core==core)$display("COVER buffer/drain-and-enqueue");
                end
                if(resp_valid && resp_ready && resp_op==0)begin if(resp_core)r1=int'(resp_data);else r0=int'(resp_data);end
                if(v[9]==3 || v[9]==4)begin
                    if(r0<0 || r1<0 || r0>1 || r1>1)fail("ORDER_LITMUS");
                    if(v[9]==4 && r0==0 && r1==0)fail("ORDER_FENCE");
                    if(v[9]==3)$display("COVER litmus/sb%0d%0d",r0,r1);
                    else $display("COVER litmus/fenced%0d%0d",r0,r1);
                end
                pending=(int'(dut.count[0])+int'(dut.count[1])+
                    ((req_valid && req_ready && op==1) ? 1 : 0)-(drain_fire ? 1 : 0))>0;
            end
            @(posedge clk);#1;checks=checks+1;@(negedge clk);
        end
        $display("COUNT steps=%0d",checks);$display("COUNT stores=%0d",stores);$display("COUNT commits=%0d",commits);
        $display("COUNT loads=%0d",loads);$display("COUNT fences=%0d",fences);$display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
