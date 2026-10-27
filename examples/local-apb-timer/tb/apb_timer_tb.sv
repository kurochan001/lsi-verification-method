`timescale 1ns/1ps
module apb_timer_tb;
    parameter WIDTH=4,WAIT_CYCLES=0,MUTATION=0;
    reg clk=0;always #5 clk=!clk;
    reg rst_n=0,psel=0,penable=0,pwrite=0;
    reg [7:0] paddr=0;reg [31:0] pwdata=0;
    wire pready,pslverr,irq,watchdog_reset_request,timer_expired;
    wire [31:0] prdata;wire [WIDTH-1:0] timer_count,watchdog_count;
    apb_timer #(.WIDTH(WIDTH),.WAIT_CYCLES(WAIT_CYCLES),.MUTATION(MUTATION)) dut(.*);
    integer fd,rc,rst,sel,access,write,address,data,ready,error,read_value,tc,wc,pending,pin,request,expired,control,tr,wr;
    integer checks=0,completions=0,errors=0,waits=0,timer_expiries=0,watchdog_resets=0;
    integer prior_tc,prior_wc,prior_control,prior_pending,transaction_waits=0;
    bit command,previous_complete=0,recovering=0;
    string vectors,wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d addr=%h control=%h timer=%0d watchdog=%0d pending=%b irq=%b",checks,paddr,dut.control,timer_count,watchdog_count,dut.pending,irq);end
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"VECTORS required");
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,apb_timer_tb);end
        fd=$fopen(vectors,"r");if(!fd) $fatal(1,"cannot open vectors");
        repeat(2) @(negedge clk);
        while(!$feof(fd)) begin
            rc=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                rst,sel,access,write,address,data,ready,error,read_value,tc,wc,pending,pin,request,expired,control,tr,wr);
            if(rc!=18) $fatal(1,"malformed vector");
            prior_tc=timer_count;prior_wc=watchdog_count;prior_control=dut.control;prior_pending=dut.pending;
            rst_n=rst;psel=sel;penable=access;pwrite=write;paddr=address;pwdata=data;
            #1;
            if(pready!==ready[0] || pslverr!==error[0]) fail("APB_RESPONSE");
            if(pready && !pwrite && prdata!==read_value[31:0]) fail("APB_READ");
            command=pready && pwrite && !pslverr && paddr==12;
            if(psel && !penable) begin
                transaction_waits=0;
                if(previous_complete && rst_n) $display("COVER apb/back-to-back");
            end
            if(rst_n && psel && penable && !pready) begin waits=waits+1;transaction_waits=transaction_waits+1;end
            if(pready) begin
                completions=completions+1;
                if(transaction_waits!=WAIT_CYCLES) fail("APB_LATENCY");
                $display("COVER apb/latency");
                if(pslverr) begin
                    errors=errors+1;
                    if(pwrite) $display("COVER apb/error-write");else $display("COVER apb/error-read");
                end else begin
                    if(pwrite) $display("COVER apb/write");else $display("COVER apb/read");
                    if(!pwrite) case(paddr)
                        0:$display("COVER register/control");4:$display("COVER register/reload-timer");
                        8:$display("COVER register/reload-watchdog");16:$display("COVER register/status");
                        28:$display("COVER register/id");default:begin end
                    endcase
                end
            end
            @(posedge clk);#1;
            if(timer_count!==tc[WIDTH-1:0] || watchdog_count!==wc[WIDTH-1:0] ||
                timer_expired!==expired[0] || watchdog_reset_request!==request[0] ||
                dut.control!==control[3:0] || dut.timer_reload!==tr[WIDTH-1:0] || dut.watchdog_reload!==wr[WIDTH-1:0]) fail("APB_TIMER_STATE");
            if(dut.pending!==pending[0] || irq!==pin[0]) fail("APB_TIMER_IRQ");
            timer_expiries=timer_expiries+timer_expired;watchdog_resets=watchdog_resets+watchdog_reset_request;
            if(!rst_n) begin
                if(psel && penable) begin $display("COVER apb/abort-reset");recovering=1;end
            end else begin
                if(timer_expired) $display("COVER timer/expiry");
                if(timer_expired && prior_control[1] && timer_count!=0) $display("COVER timer/periodic-reload");
                if(watchdog_reset_request) $display("COVER watchdog/timeout");
                if(command && pwdata[2] && !pwdata[1] && prior_wc==1 && prior_control[2] && !watchdog_reset_request)
                    $display("COVER watchdog/kick-on-expiry");
                if(command && pwdata[1] && pwdata[2]) $display("COVER watchdog/load-priority");
                if(timer_expired && watchdog_reset_request) begin
                    $display("COVER cross/simultaneous");
                    if(recovering) begin $display("COVER reset/recovery");recovering=0;end
                end
                if(dut.pending && !dut.control[3] && !irq) $display("COVER irq/masked");
                if(irq) $display("COVER irq/unmasked");
                if(command && pwdata[3] && prior_pending && !timer_expired && !dut.pending) $display("COVER irq/clear");
                if(command && pwdata[3] && timer_expired && dut.pending) $display("COVER cross/clear-expiry");
                if(command && pwdata[0] && prior_tc==1 && prior_control[0] && !timer_expired) $display("COVER cross/load-expiry");
            end
            previous_complete=ready && rst;
            checks=checks+1;@(negedge clk);
        end
        $fclose(fd);
        $display("COUNT completions=%0d",completions);$display("COUNT errors=%0d",errors);$display("COUNT waits=%0d",waits);
        $display("COUNT timer_expiries=%0d",timer_expiries);$display("COUNT watchdog_resets=%0d",watchdog_resets);
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
