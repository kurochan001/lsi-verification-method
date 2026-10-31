`timescale 1ns/1ps
module scan_tb;
    parameter REVERSE=0,MUTATION=0;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,scan_enable=0,scan_in=0,fault_enable=0,fault_value=0;
    reg [1:0] primary=0;reg [2:0] fault_site=0;
    wire [3:0] q;wire scan_out;
    scan_logic #(.REVERSE(REVERSE),.MUTATION(MUTATION)) dut(.*);
    integer fd,n,checks=0,previous_phase=0,j,detected;
    reg [13:0] faults_seen=0;reg [63:0] v[0:10];string vectors,wave;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"step=%0d",checks);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("WAVE=%s",wave))$fatal(1,"arguments required");
        $dumpfile(wave);$dumpvars(0,scan_tb);fd=$fopen(vectors,"r");if(!fd)$fatal(1,"missing input");
        repeat(2)@(negedge clk);
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10]);if(n!=11)$fatal(1,"bad row");
            rst_n=v[0][0];scan_enable=v[1][0];scan_in=v[2][0];primary=v[3][1:0];fault_enable=v[4][0];fault_site=v[5][2:0];fault_value=v[6][0];#1;
            if(q!==v[7][3:0] || scan_out!==v[8][0])begin
                if(previous_phase==2 || previous_phase==0)fail("SCAN_CAPTURE");else fail("SCAN_SHIFT");
            end
            if(!rst_n)$display("COVER reset/clears");
            else begin
                if(scan_enable)begin
                    if(scan_in)$display("COVER scan/shift-one");else $display("COVER scan/shift-zero");
                end
                if(v[9]==2)begin
                    $display("COVER scan/capture");
                    if(!fault_enable)$display("COVER functional/no-fault");
                    else begin
                        if(fault_value)$display("COVER fault/sa1");else $display("COVER fault/sa0");
                        if(fault_site==5 && !fault_value)$display("COVER fault/redundant");
                    end
                end
                if(v[9]==3)begin
                    $display("COVER scan/unload");
                    if(fault_enable && scan_out!=v[10][0])begin
                        faults_seen[2*int'(fault_site)+int'(fault_value)]=1;
                        $display("COVER fault/observable");
                    end
                end
            end
            previous_phase=int'(v[9]);@(posedge clk);#1;checks=checks+1;@(negedge clk);
        end
        detected=0;for(j=0;j<14;j=j+1)if(faults_seen[j])detected=detected+1;
        $display("COUNT steps=%0d",checks);$display("COUNT detectable_faults=%0d",detected);
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
