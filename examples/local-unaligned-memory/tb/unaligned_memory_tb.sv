`timescale 1ns/1ps
module unaligned_memory_tb;
    parameter integer DATA_W=32, DEPTH=16, BIG_ENDIAN=0, MUTATION=0;
    localparam integer AW=$clog2(DEPTH), BYTES=DATA_W/8;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0, req_valid=0, req_write=0, rsp_ready=0, fault_second=0;
    reg [15:0] req_address=0;
    reg [3:0] req_size=0;
    reg [DATA_W-1:0] req_data=0;
    wire req_ready,rsp_valid,rsp_error,native_enable,native_write;
    wire [DATA_W-1:0] rsp_data;
    wire [AW-1:0] native_address;
    unaligned_memory #(.DATA_W(DATA_W),.DEPTH(DEPTH),.BIG_ENDIAN(BIG_ENDIAN),.MUTATION(MUTATION)) dut(.*);
    integer fd,n,checks=0,expected_checks,seed,native_count=0,before_count;
    reg [127:0] row[0:8];
    reg [DATA_W+1:0] held;
    string vectors,wave,test_name;
    always @(posedge clk)if(native_enable)native_count<=native_count+1;

    task fail(input string reason);
        $display("CHECK_FAIL UNALIGNED_MEMORY");
        $fatal(1,"case=%s seed=%0d step=%0d width=%0d depth=%0d clock_ns=10 endian=%0d address=%h size=%0d expected=%h actual=%h error=%b native_count=%0d reason=%s",
            test_name,seed,checks,DATA_W,DEPTH,BIG_ENDIAN,row[1],row[2],row[5],rsp_data,rsp_error,native_count-before_count,reason);
    endtask

    task reset_controller;
        @(negedge clk);rst_n=0;req_valid=0;rsp_ready=0;
        repeat(2)@(negedge clk);
        rst_n=1;
    endtask

    task request;
        @(negedge clk);before_count=native_count;
        req_valid=1;req_write=(row[0]!=2);req_address=16'(row[1]);req_size=4'(row[2]);
        req_data=DATA_W'(row[3]);fault_second=row[4][0];
        do @(posedge clk);while(req_ready !== 1'b1);
        @(negedge clk);req_valid=0;
        // Accepted payload must be latched, including the fault selection.
        req_address=~req_address;req_size=0;req_data=~req_data;fault_second=~fault_second;
        if(row[0]==3)begin
            wait(native_count>before_count);
            @(negedge clk);rst_n=0;
            repeat(2)@(negedge clk);
            if(rsp_valid !== 0 || native_count-before_count!=1)fail("reset did not abort the second word");
            rst_n=1;$display("COVER reset/partial");
        end else begin
            wait(rsp_valid === 1'b1);#1;
            if(rsp_data !== DATA_W'(row[5]) || rsp_error !== row[6][0] || native_count-before_count!=int'(row[7]))
                fail("response or native access count differs");
            held={rsp_valid,rsp_data,rsp_error};
            repeat(3)begin
                @(negedge clk);
                if({rsp_valid,rsp_data,rsp_error} !== held || req_ready !== 0)fail("response not held");
            end
            $display("COVER response/stall");
            if(row[0]==2)$display("COVER access/read");else $display("COVER access/write");
            if(row[7]==2)$display("COVER split/cross-word");
            if(row[7]==0 && rsp_error)$display("COVER bounds/rejected");
            if(row[7]==1 && row[4]!=0 && rsp_error)begin
                $display("EXPECTED_LIMITATION second-word-error-retains-first-word");$display("COVER error/partial");
            end
            if(row[2]==1 && row[0]==2)$display("COVER endian/mapped");
            rsp_ready=1;
            @(negedge clk);rsp_ready=0;
        end
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)||!$value$plusargs("CHECKS=%d",expected_checks)||
            !$value$plusargs("SEED=%d",seed)||!$value$plusargs("CASE=%s",test_name))$fatal(1,"arguments required");
        if($value$plusargs("WAVE=%s",wave))begin $dumpfile(wave);$dumpvars(0,unaligned_memory_tb);end
        fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");
        while(!$feof(fd))begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h\n",row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8]);
            if(n!=9)$fatal(1,"bad vector");
            if(row[0]==0)reset_controller();else request();
            checks=checks+1;
        end
        if(checks!=expected_checks)fail("completion count differs");
        $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
    end
    initial begin #10000000;fail("timeout");end
endmodule
