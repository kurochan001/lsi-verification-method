`timescale 1ns/1ps
module timer_watchdog_tb;
    parameter WIDTH=4, MUTATION=0;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0, timer_enable=0, periodic=0, timer_load=0;
    reg watchdog_enable=0, watchdog_load=0, kick=0, clear_irq=0;
    reg [WIDTH-1:0] timer_reload=0, watchdog_reload=0;
    wire [WIDTH-1:0] timer_count, watchdog_count;
    wire irq, watchdog_reset_request, timer_expired;
    timer_watchdog #(.WIDTH(WIDTH),.MUTATION(MUTATION)) dut(.*);
    integer er,ete,ep,etl,etr,ewe,ewl,ewr,ek,ec,etc,ewc,ei,ew,et;
    integer fd,rc,checks=0,timer_expiries=0,watchdog_resets=0;
    integer pt=0,pw=0,pi=0;
    reg had_active_reset=0;
    string vectors,wave;
    task fail(input string label);
        begin
            $display("CHECK_FAIL %s",label);
            $fatal(1,"cycle=%0d timer=%0d watchdog=%0d irq=%b request=%b expired=%b",checks,timer_count,watchdog_count,irq,watchdog_reset_request,timer_expired);
        end
    endtask
    initial begin
        if (!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"VECTORS required");
        if ($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,timer_watchdog_tb);end
        fd=$fopen(vectors,"r");if (!fd) $fatal(1,"cannot open vectors");
        // Known initial reset, outside the vector checks.
        repeat(2) @(negedge clk);
        while (!$feof(fd)) begin
            rc=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                er,ete,ep,etl,etr,ewe,ewl,ewr,ek,ec,etc,ewc,ei,ew,et);
            if(rc!=15) $fatal(1,"malformed vector");
            pt=timer_count;pw=watchdog_count;pi=irq;
            rst_n=er;timer_enable=ete;periodic=ep;timer_load=etl;timer_reload=etr;
            watchdog_enable=ewe;watchdog_load=ewl;watchdog_reload=ewr;kick=ek;clear_irq=ec;
            @(posedge clk);#1;
            if(timer_count!==etc[WIDTH-1:0] || timer_expired!==et[0]) fail("TIMER_STATE");
            if(irq!==ei[0]) fail("TIMER_IRQ");
            if(watchdog_count!==ewc[WIDTH-1:0] || watchdog_reset_request!==ew[0]) fail("WDG_STATE");
            timer_expiries=timer_expiries+timer_expired;
            watchdog_resets=watchdog_resets+watchdog_reset_request;
            if(!rst_n) begin
                if(pt!=0 || pw!=0 || pi!=0) begin
                    $display("COVER reset/active");had_active_reset=1;
                end
            end else begin
                if(timer_load) begin
                    if(timer_reload==0) $display("COVER timer/load-zero");
                    if(timer_reload==1) $display("COVER timer/load-one");
                    if(&timer_reload) $display("COVER timer/load-max");
                    if(pt==1 && timer_enable) $display("COVER timer/load-on-expiry");
                end
                if(timer_expired && !periodic) $display("COVER timer/one-shot-expiry");
                if(timer_expired && periodic && timer_count!=0) $display("COVER timer/periodic-reload");
                if(timer_expired && periodic && timer_count==1) $display("COVER timer/periodic-one");
                if(!timer_enable && !timer_load && pt>0) $display("COVER timer/disabled-hold");
                if(timer_expired && clear_irq && irq) $display("COVER irq/set-wins");
                if(pi && clear_irq && !timer_expired && !irq) $display("COVER irq/clear");
                if(watchdog_load && watchdog_reload==0) $display("COVER watchdog/load-zero");
                if(watchdog_load && (&watchdog_reload)) $display("COVER watchdog/load-max");
                if(watchdog_load && watchdog_enable && kick) $display("COVER watchdog/load-priority");
                if(watchdog_reset_request) $display("COVER watchdog/timeout");
                if(pw==1 && watchdog_enable && kick && !watchdog_load && !watchdog_reset_request)
                    $display("COVER watchdog/kick-on-expiry");
                if(!watchdog_enable && !watchdog_load && pw>0 && kick) $display("COVER watchdog/disabled-hold");
                if(timer_expired && watchdog_reset_request) $display("COVER combined/expiry");
                if(had_active_reset && timer_expired && watchdog_reset_request) begin
                    $display("COVER reset/recovery");had_active_reset=0;
                end
                if(timer_count==0 && watchdog_count==0 && !irq && !timer_expired && !watchdog_reset_request
                    && !timer_load && !watchdog_load) $display("COVER completion/idle");
            end
            checks=checks+1;
            @(negedge clk);
        end
        $fclose(fd);
        $display("COUNT timer_expiries=%0d",timer_expiries);
        $display("COUNT watchdog_resets=%0d",watchdog_resets);
        $display("RESULT PASS checks=%0d",checks);
        $finish;
    end
endmodule
