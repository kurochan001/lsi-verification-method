`timescale 1ns/1ps
module lbist_tb;
    parameter integer PATTERNS=16, MUTATION=0;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, test_mode=0, start=0, fault_enable=0, fault_value=0;
    reg [7:0] seed=0, expected_signature=0;
    reg [3:0] normal_in=0, response_xor=0;
    reg [1:0] fault_site=0;
    wire [3:0] normal_out, raw_response;
    wire busy, done, failed, seed_error;
    wire [7:0] signature, prpg, pattern_count;
    lbist #(.PATTERNS(PATTERNS),.MUTATION(MUTATION)) dut(.*);
    reg [63:0] v[0:20];
    reg old_busy, old_done;
    reg [7:0] old_count, detected=0;
    integer fd, n, checks=0, completed=0, alias_changes=0, j, faults;
    string vectors, wave;

    task fail(input string label);
        begin $display("CHECK_FAIL %s",label); $fatal(1,"step=%0d",checks); end
    endtask

    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave))
            $fatal(1,"arguments required");
        $dumpfile(wave); $dumpvars(0,lbist_tb);
        fd=$fopen(vectors,"r"); if (!fd) $fatal(1,"missing vectors");
        repeat(2) @(negedge clk);
        while (!$feof(fd)) begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                      v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],
                      v[11],v[12],v[13],v[14],v[15],v[16],v[17],v[18],v[19],v[20]);
            if (n!=21) $fatal(1,"bad vector");
            old_busy=busy; old_done=done; old_count=pattern_count;
            rst_n=v[0][0]; test_mode=v[1][0]; start=v[2][0]; seed=v[3][7:0];
            expected_signature=v[4][7:0]; normal_in=v[5][3:0];
            fault_enable=v[6][0]; fault_site=v[7][1:0]; fault_value=v[8][0];
            response_xor=v[9][3:0];
            #1;
            if (normal_out!==v[18][3:0]) fail("LBIST_ISOLATION");
            if (raw_response!==v[19][3:0]) fail("LBIST_LOGIC");
            if (rst_n && test_mode && old_busy && v[10]==20 && raw_response!==v[20][3:0])
                alias_changes=alias_changes+1;
            @(posedge clk); #1;
            if (busy!==v[11][0] || done!==v[12][0] || seed_error!==v[14][0]
                || pattern_count!==v[17][7:0]) fail("LBIST_CONTROL");
            if (prpg!==v[16][7:0]) fail("LBIST_SEQUENCE");
            if (signature!==v[15][7:0]) fail("LBIST_SIGNATURE");
            if (failed!==v[13][0]) fail("LBIST_RESULT");
            if (!rst_n) begin
                $display("COVER reset/clears");
                if (old_busy) $display("COVER abort/reset");
            end else if (!test_mode) begin
                if (start && !old_busy) $display("COVER mode/start-guard");
                if (old_busy) $display("COVER abort/mode");
                if (normal_out!=0) $display("COVER normal/restore");
            end else begin
                if (v[19]!=0 && normal_out==0) $display("COVER isolation/test");
                if (!old_busy && start && seed==0 && seed_error) $display("COVER seed/reject-zero");
                if (!old_busy && busy) $display("COVER control/start");
                if (old_busy) begin
                    $display("COVER prpg/advance"); $display("COVER signature/update");
                    if (start && pattern_count==old_count+8'd1) begin
                        $display("COVER control/busy-ignore");
                        if (seed==0) $display("COVER config/latched");
                    end
                    if (done) begin
                        completed=completed+1;
                        if (int'(pattern_count)==PATTERNS) $display("COVER done/exact-count");
                        if (failed) $display("COVER result/fail"); else $display("COVER result/pass");
                        if (fault_enable && failed) detected[{fault_site,fault_value}]=1;
                    end
                end
                if (old_done && done && !start) $display("COVER done/held");
            end
            checks=checks+1; @(negedge clk);
        end
        if (detected==8'hff) $display("COVER fault/all-eight");
        faults=0; for (j=0;j<8;j=j+1) if (detected[j]) faults=faults+1;
        $display("COUNT steps=%0d",checks);
        $display("COUNT completed=%0d",completed);
        $display("COUNT detected_faults=%0d",faults);
        $display("COUNT alias_changes=%0d",alias_changes);
        $display("RESULT PASS checks=%0d",checks); $finish;
    end
endmodule
