`timescale 1ns/1ps
module bridge_tb;
    parameter BUS=0,WAIT_CYCLES=0,MUTATION=0;
    reg clk=0;always #5 clk=!clk;
    reg rst_n=0,hsel=0,hwrite=0;reg [1:0] htrans=0;reg [9:0] haddr=0;reg [2:0] hsize=2;reg [31:0] hwdata=0;
    reg awvalid=0,wvalid=0,arvalid=0,bready=0,rready=0;reg [9:0] awaddr=0,araddr=0;reg [31:0] wdata=0;reg [3:0] wstrb=15;
    wire hready,hresp,awready,wready,arready,bvalid,rvalid;wire [1:0] bresp,rresp,psel;
    wire [31:0] hrdata,rdata,pwdata,apb_data;wire penable,pwrite,apb_ready,apb_error,irq,watchdog_reset_request,timer_expired;
    wire [7:0] paddr;wire [3:0] timer_count,watchdog_count;
    bus_bridge #(.BUS(BUS),.WAIT_CYCLES(WAIT_CYCLES),.MUTATION(MUTATION)) dut(.*);
    generate if(BUS==0) begin
        ahb_protocol_checker c(clk,rst_n,hsel,hready,hresp,hwrite,htrans,hsize,3'b000,haddr,hwdata,hrdata);
    end else begin
        axi_lite_protocol_checker #(.ADDR_WIDTH(10)) c(clk,rst_n,awvalid,awready,wvalid,wready,arvalid,arready,bvalid,bready,rvalid,rready,
            awaddr,araddr,3'b000,3'b000,wdata,rdata,wstrb,bresp,rresp);
    end endgenerate
    integer fd,fields,v[0:45],checks=0,reads=0,writes=0,apb=0,expiries=0,watchdogs=0;
    bit recovering=0;string vectors,wave;
    task fail(input string label);begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d bus=%0d psel=%b paddr=%h",checks,BUS,psel,paddr);end endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"vectors required");
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,bridge_tb);end
        fd=$fopen(vectors,"r");if(!fd) $fatal(1,"cannot open vectors");repeat(2) @(negedge clk);
        while(!$feof(fd)) begin
            fields=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10],v[11],v[12],v[13],v[14],v[15],v[16],v[17],v[18],v[19],v[20],v[21],v[22],v[23],v[24],v[25],v[26],v[27],v[28],v[29],v[30],v[31],v[32],v[33],v[34],v[35],v[36],v[37],v[38],v[39],v[40],v[41],v[42],v[43],v[44],v[45]);
            if(fields!=46) $fatal(1,"bad vector");
            if(!v[0] && (psel!=0 || v[44] || bvalid || rvalid)) begin $display("COVER reset/active");recovering=1;end
            rst_n=v[0];hsel=v[1];htrans=v[2];haddr=v[3];hwrite=v[4];hsize=v[5];hwdata=v[6];
            awvalid=v[7];awaddr=v[8];wvalid=v[9];wdata=v[10];wstrb=v[11];arvalid=v[12];araddr=v[13];bready=v[14];rready=v[15];
            #1;
            if(hready!==v[16][0] || hresp!==v[17][0] || awready!==v[19][0] || wready!==v[20][0] || arready!==v[21][0] ||
                bvalid!==v[22][0] || rvalid!==v[24][0]) fail("BRIDGE_RESPONSE");
            if((BUS==0 && v[44] && !v[45] && hready && !hresp && hrdata!==v[18][31:0]) ||
                (bvalid && bresp!==v[23][1:0]) || (rvalid && (rdata!==v[25][31:0] || rresp!==v[26][1:0]))) fail("BRIDGE_RESPONSE");
            if(psel!==v[27][1:0] || penable!==v[28][0] || pwrite!==v[29][0] || paddr!==v[30][7:0] || pwdata!==v[31][31:0]) fail("BRIDGE_APB");
            if(apb_ready!==v[32][0] || apb_error!==v[33][0] || (psel!=0 && penable && apb_ready && !pwrite && apb_data!==v[34][31:0])) fail("BRIDGE_TARGET");
            if(rst_n) begin
                if((BUS==0 && v[44] && hready && hsel && htrans[1]) ||
                   (BUS==1 && awvalid && awready && wvalid && wready && arvalid && arready)) $display("COVER upstream/overlap");
                if(psel!=0 && !penable) $display("COVER apb/setup");
                if(psel!=0 && penable) $display("COVER apb/access");
                if(psel!=0 && penable && apb_ready) begin
                    apb=apb+1;$display("COVER apb/wait-policy");
                    if(psel[0]) $display("COVER target/basic");else $display("COVER target/timer");
                    if(apb_error) $display("COVER apb/error");
                end
                if((BUS==0 && v[44] && hready) || (BUS==1 && ((bvalid && bready) || (rvalid && rready)))) begin
                    if((BUS==0 && v[45]) || (BUS==1 && bvalid && bready)) begin writes=writes+1;$display("COVER upstream/write");end
                    if((BUS==0 && !v[45]) || (BUS==1 && rvalid && rready)) begin reads=reads+1;$display("COVER upstream/read");end
                    if((BUS==0 && hresp) || (BUS==1 && ((bvalid && bready && bresp!=0) || (rvalid && rready && rresp!=0)))) $display("COVER response/error");
                    if((BUS==0 && !hresp) || (BUS==1 && ((bvalid && bready && bresp==0) || (rvalid && rready && rresp==0)))) $display("COVER response/okay");
                    if(recovering) begin $display("COVER reset/recovery");recovering=0;end
                end
                if((BUS==0 && hsel && htrans[1] && hready && haddr[9]) || (BUS==1 && ((awvalid && awready && awaddr[9]) || (arvalid && arready && araddr[9])))) $display("COVER decode/unmapped");
                if((BUS==0 && hsel && htrans[1] && hready && hsize!=2) || (BUS==1 && wvalid && wready && wstrb!=0 && wstrb!=15)) $display("COVER policy/unsupported");
            end
            @(posedge clk);#1;
            if(dut.basic.config_value!==v[35][31:0] || timer_count!==v[36][3:0] || watchdog_count!==v[37][3:0] || irq!==v[38][0] ||
                watchdog_reset_request!==v[39][0] || timer_expired!==v[40][0] || dut.timer.control!==v[41][3:0] ||
                dut.timer.timer_reload!==v[42][3:0] || dut.timer.watchdog_reload!==v[43][3:0]) fail("BRIDGE_STATE");
            expiries=expiries+timer_expired;watchdogs=watchdogs+watchdog_reset_request;
            if(timer_expired) $display("COVER timer/expiry");if(irq) $display("COVER timer/irq");
            if(watchdog_reset_request) $display("COVER watchdog/timeout");
            checks=checks+1;@(negedge clk);
        end
        $fclose(fd);$display("COUNT reads=%0d",reads);$display("COUNT writes=%0d",writes);$display("COUNT apb=%0d",apb);
        $display("COUNT expiries=%0d",expiries);$display("COUNT watchdogs=%0d",watchdogs);
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
