`timescale 1ns/1ps
module semaphore_tb;
    parameter WIN=8, KMAX=2, MUTATION=0;
    reg clk=0, rst_n=1, claim=0, release_req=0;
    reg [1:0] slot=0, inc=0, rearm=0, events=0;
    wire [3:0] owned;
    wire grant, window_active;
    wire [1:0] done, passed, suppressed;
    wire [15:0] counts;
    hw_semaphore #(.WIN(WIN), .KMAX(KMAX), .MUTATION(MUTATION)) dut(.*);
    always #5 clk = ~clk;
    integer n, fd, checks=0;
    reg [31:0] v[0:13];
    reg [3:0] was_owned, released_slots=0;
    reg [1:0] was_done, was_suppressed;
    reg was_active, had_reset=0;
    string vectors, wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label); $fatal(1,"row=%0d",checks); end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors) || !$value$plusargs("WAVE=%s",wave)) $fatal(1);
        fd=$fopen(vectors,"r"); if (!fd) $fatal(1);
        $dumpfile(wave); $dumpvars(0,semaphore_tb);
        while (!$feof(fd)) begin
            n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                      v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13]);
            if (n!=14) $fatal(1,"bad row");
            @(negedge clk);
            was_owned=owned; was_done=done; was_active=window_active; was_suppressed=suppressed;
            rst_n=v[0]; claim=v[1]; release_req=v[2]; slot=v[3]; inc=v[4]; rearm=v[5]; events=v[6];
            @(posedge clk); #1;
            if (owned !== v[7][3:0] || grant !== v[8][0]) fail("SEM_STATE");
            if (counts !== v[9][15:0] || done !== v[10][1:0]) fail("FENCE");
            if (passed !== v[11][1:0] || suppressed !== v[12][1:0] || window_active !== v[13][0]) fail("IRQ_LIMIT");
            if (!rst_n) begin released_slots=0; had_reset=1; end
            else begin
                if (grant) begin
                    $display("COVER sem/grant");
                    if (released_slots[slot]) $display("COVER sem/reacquire");
                    if (had_reset) begin $display("COVER reset/recovery"); had_reset=0; end
                end
                if (claim && !release_req && was_owned[slot] && !grant) $display("COVER sem/busy");
                if (release_req && was_owned[slot] && !owned[slot]) begin
                    $display("COVER sem/release"); released_slots[slot]=1;
                end
                if (|(done & ~was_done)) $display("COVER fence/done");
                if (|(inc & was_done & done)) begin
                    $display("COVER fence/once");
                    if (counts[7:0]==255 && inc[0]) $display("COVER fence/overflow-hold");
                end
                if (|(was_done & rearm & ~done)) $display("COVER fence/rearm");
                if (passed!=0) $display("COVER irq/pass");
                if (suppressed!=0) $display("COVER irq/suppress");
                if (was_active && !window_active && passed!=0) $display("COVER irq/window-rollover");
                if (was_suppressed!=0 && passed!=0) $display("COVER irq/suppress-rearm");
            end
            checks=checks+1;
        end
        $fclose(fd); $display("COUNT steps=%0d",checks); $display("RESULT PASS checks=%0d",checks); $finish;
    end
endmodule
