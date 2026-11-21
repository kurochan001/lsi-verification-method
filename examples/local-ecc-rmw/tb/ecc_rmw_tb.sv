`timescale 1ns/1ps
module ecc_rmw_tb;
    parameter integer DATA_W=32, DEPTH=8, MUTATION=0;
    localparam integer AW=$clog2(DEPTH), CODE_W=DATA_W+(DATA_W==64 ? 7:6)+1;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0, req_valid=0, req_write=0, rsp_ready=0, scrub_enable=0, inject_valid=0;
    reg [AW-1:0] req_addr=0, inject_addr=0;
    reg [DATA_W-1:0] req_data=0;
    reg [DATA_W/8-1:0] req_strb=0;
    reg [CODE_W-1:0] inject_mask=0;
    wire req_ready, rsp_valid, rsp_corrected, rsp_uncorrectable, rsp_error;
    wire inject_ready, busy, scrub_done, scrub_corrected, scrub_uncorrectable;
    wire [DATA_W-1:0] rsp_data;
    ecc_rmw_ram #(.DATA_W(DATA_W),.DEPTH(DEPTH),.MUTATION(MUTATION)) dut(.*);
    integer fd, n, checks=0, expected_checks, seed, sweeps;
    reg [127:0] row[0:9];
    reg [DATA_W+3:0] held;
    string vectors, wave, test_name;

    task fail(input string reason);
        $display("CHECK_FAIL ECC_RMW");
        $fatal(1,"case=%s seed=%0d step=%0d width=%0d depth=%0d clock_ns=10 op=%0d addr=%h strb=%h fault_mask=%h expected=%h actual=%h ce=%b ue=%b error=%b reason=%s",
            test_name,seed,checks,DATA_W,DEPTH,row[0],row[1],row[3],row[4],row[5],rsp_data,rsp_corrected,rsp_uncorrectable,rsp_error,reason);
    endtask

    task reset_controller;
        @(negedge clk);rst_n=0;req_valid=0;inject_valid=0;scrub_enable=0;rsp_ready=0;
        repeat(2) @(negedge clk);
        rst_n=1;
    endtask

    task request(input bit abort_request);
        @(negedge clk);
        req_valid=1;req_write=(row[0]!=2);req_addr=AW'(row[1]);
        req_data=DATA_W'(row[2]);req_strb=(DATA_W/8)'(row[3]);
        scrub_enable=(row[0]==6);
        do @(posedge clk); while(req_ready !== 1'b1);
        @(negedge clk);req_valid=0;
        req_addr=~req_addr;req_data=~req_data;req_strb=~req_strb;
        if(row[0]==7)begin
            req_valid=1;req_write=1;req_addr=AW'(row[1]);req_data=DATA_W'(16'hbb00);req_strb=(DATA_W/8)'(2);
        end
        if(abort_request) begin
            // READ has completed; DECODE and the write commit have not.
            @(negedge clk);rst_n=0;
            repeat(2) @(negedge clk);
            if(rsp_valid !== 0) fail("aborted request produced a response");
            rst_n=1;$display("COVER reset/abort");
        end else begin
            while(rsp_valid !== 1'b1)begin
                if(req_ready !== 0)fail("request was accepted inside an RMW");
                @(negedge clk);
            end
            #1;
            if(rsp_data !== DATA_W'(row[5]) || rsp_corrected !== row[6][0] ||
                rsp_uncorrectable !== row[7][0] || rsp_error !== row[8][0]) fail("response differs");
            held={rsp_valid,rsp_data,rsp_corrected,rsp_uncorrectable,rsp_error};
            repeat(3) begin
                @(negedge clk);
                if({rsp_valid,rsp_data,rsp_corrected,rsp_uncorrectable,rsp_error} !== held)
                    fail("response changed during backpressure");
                if(req_ready !== 0) fail("RMW/response did not serialize access");
            end
            $display("COVER response/stall");
            if(row[0]==2) $display("COVER access/read");
            if(row[0]!=2 && row[3]!=0 && row[3]!=(1<<(DATA_W/8))-1) $display("COVER access/partial");
            if(row[0]!=2 && row[3]==0) $display("COVER access/zero-mask");
            if(rsp_corrected) $display("COVER fault/corrected");
            if(rsp_uncorrectable) $display("COVER fault/uncorrectable");
            if(scrub_enable) $display("COVER race/foreground");
            rsp_ready=1;
            @(negedge clk);rsp_ready=0;scrub_enable=0;
            if(row[0]==7)begin
                do @(posedge clk);while(req_ready !== 1'b1);
                @(negedge clk);req_valid=0;
                wait(rsp_valid === 1'b1);#1;
                if({rsp_data,rsp_corrected,rsp_uncorrectable,rsp_error} !== (DATA_W+3)'(0))fail("queued byte write failed");
                @(negedge clk);rsp_ready=1;
                @(negedge clk);rsp_ready=0;$display("COVER race/queued-write");
            end
        end
    endtask

    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("CHECKS=%d",expected_checks) ||
           !$value$plusargs("SEED=%d",seed) || !$value$plusargs("CASE=%s",test_name)) $fatal(1,"arguments required");
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,ecc_rmw_tb);end
        fd=$fopen(vectors,"r");if(!fd)$fatal(1,"vectors missing");
        while(!$feof(fd)) begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h\n",row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8],row[9]);
            if(n!=10)$fatal(1,"bad vector");
            case(row[0])
                0: reset_controller();
                1,2,6,7: request(0);
                3: begin
                    @(negedge clk);inject_valid=1;inject_addr=AW'(row[1]);inject_mask=CODE_W'(row[4]);
                    do @(posedge clk);while(inject_ready !== 1'b1);
                    @(negedge clk);inject_valid=0;
                end
                4: begin
                    @(negedge clk);scrub_enable=1;sweeps=0;
                    while(sweeps<DEPTH) begin
                        @(posedge clk);#1;
                        if(scrub_done === 1'b1)sweeps=sweeps+1;
                        if($isunknown({scrub_done,scrub_corrected,scrub_uncorrectable}))fail("unknown scrub status");
                    end
                    @(negedge clk);scrub_enable=0;$display("COVER scrub/completed");
                end
                5: request(1);
                default:$fatal(1,"unknown operation");
            endcase
            checks=checks+1;
        end
        if(checks!=expected_checks)fail("completion count differs");
        $display("COUNT steps=%0d",checks);$display("RESULT PASS checks=%0d",checks);$finish;
    end
    // A hang is not a detection: it gets its own label, so a mutation that only
    // stalls the bench is reported as an error instead of the expected ECC_RMW.
    initial begin
        #10000000;$display("CHECK_FAIL ECC_RMW_TIMEOUT");
        $fatal(1,"case=%s seed=%0d step=%0d reason=timeout",test_name,seed,checks);
    end
endmodule
