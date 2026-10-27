`timescale 1ns/1ps
module reset_tb;
    reg clk=0;always #5 clk=!clk;
    reg rst_n=0;
    reg hsel=0,hwrite=0;reg [1:0] htrans=0;reg [2:0] hsize=2,hburst=0;
    reg [9:0] haddr=0;reg [31:0] hwdata=0;
    wire hready,hresp;wire [31:0] hrdata;
    ahb_regs #(.WAIT_CYCLES(3)) ahb(clk,rst_n,hsel,hready,hwrite,htrans,hsize,hburst,haddr,hwdata,hready,hresp,hrdata);
    ahb_protocol_checker ahb_check(clk,rst_n,hsel,hready,hresp,hwrite,htrans,hsize,hburst,haddr,hwdata,hrdata);
    reg awvalid=0,wvalid=0,arvalid=0,bready=0,rready=0;
    reg [7:0] awaddr=0,araddr=0;reg [2:0] awprot=0,arprot=0;
    reg [31:0] wdata=0;reg [3:0] wstrb=15;
    wire awready,wready,arready,bvalid,rvalid;wire [1:0] bresp,rresp;wire [31:0] rdata;
    axi_lite_regs axi(clk,rst_n,awvalid,wvalid,arvalid,bready,rready,awaddr,araddr,awprot,arprot,wdata,wstrb,
                      awready,wready,arready,bvalid,rvalid,bresp,rresp,rdata);
    axi_lite_protocol_checker axi_check(clk,rst_n,awvalid,awready,wvalid,wready,arvalid,arready,bvalid,bready,rvalid,rready,
        awaddr,araddr,awprot,arprot,wdata,rdata,wstrb,bresp,rresp);
    integer checks=0,offset;bit ready_sample;string wave;
    task ahb_write;
        begin
            hsel=1;htrans=2;hwrite=1;haddr=0;@(posedge clk);#1;@(negedge clk);
            hsel=0;htrans=0;hwdata=32'ha5a55a5a;
            ready_sample=0;
            for(integer i=0;i<12 && !ready_sample;i=i+1) begin @(posedge clk);ready_sample=hready;#1;@(negedge clk);end
            if(!ready_sample || ahb.registers[0]!==32'ha5a55a5a) $fatal(1,"AHB setup write failed");
        end
    endtask
    task axi_write;
        begin
            awvalid=1;wvalid=1;wdata=32'h12345678;@(posedge clk);
            if(!awready || !wready) $fatal(1,"AXI setup acceptance failed");
            #1;@(negedge clk);awvalid=0;wvalid=0;wdata=~wdata;
            for(integer i=0;i<12 && !bvalid;i=i+1) @(negedge clk);
            if(!bvalid || bresp!=0 || axi.registers[0]!==32'h12345678) $fatal(1,"AXI setup write failed");
            bready=1;@(posedge clk);#1;@(negedge clk);bready=0;
        end
    endtask
    initial begin
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,reset_tb);end
        repeat(2) @(negedge clk);rst_n=1;
        for(integer phase=0;phase<3;phase=phase+1) begin
            ahb_write();axi_write();
            arvalid=1;araddr=0;@(posedge clk);if(!arready) $fatal(1,"AR setup failed");
            #1;@(negedge clk);arvalid=0;
            for(integer i=0;i<12 && !rvalid;i=i+1) @(negedge clk);
            if(!rvalid) $fatal(1,"R setup failed");
            hsel=1;htrans=2;hwrite=1;haddr=4;@(posedge clk);#1;@(negedge clk);hsel=0;htrans=0;hwdata=32'hffffffff;
            offset=phase==0 ? 1 : phase==1 ? 2 : 6;
            #offset;rst_n=0;#0.1;
            if(hready!==1 || hresp!==0 || bvalid!==0 || rvalid!==0) $fatal(1,"async reset output failed");
            for(integer i=0;i<4;i=i+1) if(ahb.registers[i]!==0 || axi.registers[i]!==0) $fatal(1,"async reset storage failed");
            #0.9;rst_n=1;hwdata=0;
            @(negedge clk);repeat(2) @(negedge clk);
            if(ahb.registers[1]!==0 || bvalid || rvalid) $fatal(1,"aborted transfer reappeared");
            $display("COVER reset/offset%0d",offset);checks=checks+1;
        end
        ahb_write();axi_write();
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
