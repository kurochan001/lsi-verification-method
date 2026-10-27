`timescale 1ns/1ps
module axi_tb;
    parameter RESP_DELAY=0,MUTATION=0;
    reg aclk=0;always #5 aclk=!aclk;
    reg aresetn=0,awvalid=0,wvalid=0,arvalid=0,bready=0,rready=0;
    reg [7:0] awaddr=0,araddr=0;reg [2:0] awprot=0,arprot=0;
    reg [31:0] wdata=0;reg [3:0] wstrb=0;
    wire awready,wready,arready,bvalid,rvalid;
    wire [1:0] bresp,rresp;wire [31:0] rdata;
    axi_lite_regs #(.RESP_DELAY(RESP_DELAY),.MUTATION(MUTATION)) dut(.*);
`ifdef BUS_VALIDATION
    axi_lite_protocol_checker protocol_checker(aclk,aresetn,awvalid,awready,wvalid,wready,arvalid,arready,bvalid,bready,rvalid,rready,
        awaddr,araddr,awprot,arprot,wdata,rdata,wstrb,bresp,rresp);
    integer perf_aw=-1,perf_w=-1,perf_ar=-1,perf_first=-1,perf_last=-1,perf_done=0;
    integer cross_order=0,cross_strobe=0,cross_bstall=0,cross_rstall=0;
`endif
    integer fd,fields,rst,av,aa,ap,wv,wd,ws,arv,ara,arp,br,rr,ear,ewr,err,ebv,ebp,erv,erd,erp;
    integer expected_regs[0:3],old_regs[0:3];
    integer checks=0,aw=0,w=0,ar=0,b=0,r=0,write_errors=0,read_errors=0,b_stalls=0,r_stalls=0;
    bit aw_seen=0,w_seen=0,ar_seen=0,previous_b_stall=0,previous_r_stall=0,recovering=0;
    bit aw_hs,w_hs,ar_hs;
    bit previous_aw_stall=0,previous_w_stall=0,previous_ar_stall=0;
    reg [10:0] previous_aw,previous_ar;reg [35:0] previous_w;
    reg [1:0] previous_bresp,previous_rresp;reg [31:0] previous_rdata;
    string vectors,wave;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label);$fatal(1,"cycle=%0d aw=%b/%b w=%b/%b b=%b/%b r=%b/%b",checks,awvalid,awready,wvalid,wready,bvalid,bready,rvalid,rready);end
    endtask
    initial begin
        if(!$value$plusargs("VECTORS=%s",vectors)) $fatal(1,"VECTORS required");
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,axi_tb);end
        fd=$fopen(vectors,"r");if(!fd) $fatal(1,"cannot open vectors");
        repeat(2) @(negedge aclk);
        while(!$feof(fd)) begin
            fields=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h %h\n",
                rst,av,aa,ap,wv,wd,ws,arv,ara,arp,br,rr,ear,ewr,err,ebv,ebp,erv,erd,erp,
                expected_regs[0],expected_regs[1],expected_regs[2],expected_regs[3]);
            if(fields!=24) $fatal(1,"malformed vector");
            if(!rst) begin
                if(aw_seen && !w_seen) $display("COVER reset/aw-only");
                if(w_seen && !aw_seen) $display("COVER reset/w-only");
                if(bvalid) $display("COVER reset/b-pending");
                if(rvalid) $display("COVER reset/r-pending");
                if(aw_seen || w_seen || ar_seen || bvalid || rvalid) recovering=1;
            end
            aresetn=rst;awvalid=av;awaddr=aa;awprot=ap;wvalid=wv;wdata=wd;wstrb=ws;
            arvalid=arv;araddr=ara;arprot=arp;bready=br;rready=rr;
            #1;
            if(!rst) begin
                previous_b_stall=0;previous_r_stall=0;aw_seen=0;w_seen=0;ar_seen=0;
                previous_aw_stall=0;previous_w_stall=0;previous_ar_stall=0;
            end
            if(previous_aw_stall && (awvalid!==1 || {awaddr,awprot}!==previous_aw)) fail("AXI_MASTER");
            if(previous_w_stall && (wvalid!==1 || {wdata,wstrb}!==previous_w)) fail("AXI_MASTER");
            if(previous_ar_stall && (arvalid!==1 || {araddr,arprot}!==previous_ar)) fail("AXI_MASTER");
            if(previous_b_stall && (bvalid!==1 || bresp!==previous_bresp)) fail("AXI_STABILITY");
            if(previous_r_stall && (rvalid!==1 || rresp!==previous_rresp || rdata!==previous_rdata)) fail("AXI_STABILITY");
            if(awready!==ear[0] || wready!==ewr[0] || arready!==err[0]) fail("AXI_READY");
            if(bvalid!==ebv[0] || rvalid!==erv[0]) fail("AXI_RESPONSE");
            if(bvalid && bresp!==ebp[1:0]) fail("AXI_RESPONSE");
            if(rvalid && (rresp!==erp[1:0] || rdata!==erd[31:0])) fail("AXI_DATA");
            if(bvalid && (!aw_seen || !w_seen)) fail("AXI_CAUSALITY");
            if(rvalid && !ar_seen) fail("AXI_CAUSALITY");
            if(awvalid && !awready) $display("COVER request/aw-held");
            if(wvalid && !wready) $display("COVER request/w-held");
            if(arvalid && !arready) $display("COVER request/ar-held");
            aw_hs=awvalid && awready;w_hs=wvalid && wready;ar_hs=arvalid && arready;
`ifdef BUS_VALIDATION
            if(aw_hs) begin perf_aw=checks;if(perf_first<0) perf_first=checks;end
            if(w_hs) begin perf_w=checks;cross_strobe=wstrb;if(perf_first<0) perf_first=checks;end
            if(ar_hs) begin perf_ar=checks;cross_rstall=0;if(perf_first<0) perf_first=checks;end
            if(aw_hs && w_hs) begin cross_order=2;cross_bstall=0;end
            else if(w_hs && aw_seen) begin cross_order=0;cross_bstall=0;end
            else if(aw_hs && w_seen) begin cross_order=1;cross_bstall=0;end
`endif
            if(aw_hs && w_hs) $display("COVER channel/together");
            else if(w_hs && aw_seen) $display("COVER channel/aw-first");
            else if(aw_hs && w_seen) $display("COVER channel/w-first");
            if(ar_hs && (aw_hs || w_hs)) $display("COVER channel/read-write");
            if(aw_hs) begin aw=aw+1;aw_seen=1;end
            if(w_hs) begin
                w=w+1;w_seen=1;$display("COVER strobe/%0d",wstrb);
                if(wstrb==15 && wdata==0) $display("COVER data/zero");
                if(wstrb==15 && wdata==32'hffffffff) $display("COVER data/ones");
                if(wstrb==15 && wdata==32'h55555555) $display("COVER data/alternating");
            end
            if(ar_hs) begin ar=ar+1;ar_seen=1;end
            if(bvalid) begin
                if(bready) begin
                    b=b+1;aw_seen=0;w_seen=0;
`ifdef BUS_VALIDATION
                    perf_done=perf_done+1;perf_last=checks;
                    $display("PERF axi-write latency=%0d cycle=%0d",checks-(perf_aw>perf_w ? perf_aw : perf_w),checks);
                    if(bresp==0) $display("CROSS axi/order%0d/strobe%0d/stall%0d",cross_order,cross_strobe==0 ? 0 : cross_strobe==15 ? 2 : 1,cross_bstall!=0);
`endif
                    if(bresp==0) $display("COVER response/b-okay");
                    else begin write_errors=write_errors+1;$display("COVER response/b-error");end
                end else begin
`ifdef BUS_VALIDATION
                    cross_bstall=cross_bstall+1;
`endif
                    b_stalls=b_stalls+1;$display("COVER backpressure/b");end
            end
            if(rvalid) begin
                if(rready) begin
                    r=r+1;ar_seen=0;
`ifdef BUS_VALIDATION
                    perf_done=perf_done+1;perf_last=checks;
                    $display("PERF axi-read latency=%0d cycle=%0d",checks-perf_ar,checks);
                    $display("CROSS axi/read/resp%0d/stall%0d",rresp,cross_rstall!=0);
`endif
                    if(rresp==0) $display("COVER response/r-okay");
                    else begin read_errors=read_errors+1;$display("COVER response/r-error");end
                    if(recovering) begin $display("COVER reset/recovery");recovering=0;end
                end else begin
`ifdef BUS_VALIDATION
                    cross_rstall=cross_rstall+1;
`endif
                    r_stalls=r_stalls+1;$display("COVER backpressure/r");end
            end
            previous_aw_stall=awvalid && !awready;previous_aw={awaddr,awprot};
            previous_w_stall=wvalid && !wready;previous_w={wdata,wstrb};
            previous_ar_stall=arvalid && !arready;previous_ar={araddr,arprot};
            previous_b_stall=bvalid && !bready;previous_bresp=bresp;
            previous_r_stall=rvalid && !rready;previous_rresp=rresp;previous_rdata=rdata;
            for(integer i=0;i<4;i=i+1) old_regs[i]=dut.registers[i];
            @(posedge aclk);#1;
            for(integer i=0;i<4;i=i+1) begin
                if(dut.registers[i]!==expected_regs[i][31:0]) fail("AXI_STATE");
                if(rst && previous_r_stall && dut.registers[i]!==old_regs[i][31:0]) $display("COVER read/snapshot");
                if(rst && ar_hs && dut.registers[i]!==old_regs[i][31:0]) $display("COVER read/same-edge");
            end
            checks=checks+1;@(negedge aclk);
        end
        $fclose(fd);
        $display("COUNT aw=%0d",aw);$display("COUNT w=%0d",w);$display("COUNT ar=%0d",ar);
        $display("COUNT b=%0d",b);$display("COUNT r=%0d",r);$display("COUNT write_errors=%0d",write_errors);
        $display("COUNT read_errors=%0d",read_errors);$display("COUNT b_stalls=%0d",b_stalls);$display("COUNT r_stalls=%0d",r_stalls);
`ifdef BUS_VALIDATION
        $display("PERF_TOTAL axi first=%0d last=%0d completed=%0d",perf_first,perf_last,perf_done);
`endif
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
