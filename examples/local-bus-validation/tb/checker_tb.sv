`timescale 1ns/1ps
module checker_tb;
    parameter BUS=0;
    reg clk=0;always #5 clk=!clk;
    reg rst_n=0,hsel=0,hready=1,hresp=0,hwrite=0;
    reg [1:0] htrans=0;reg [2:0] hsize=2,hburst=0;
    reg [9:0] haddr=0;reg [31:0] hwdata=0,hrdata=0;
    reg awvalid=0,awready=1,wvalid=0,wready=1,arvalid=0,arready=1,bvalid=0,bready=1,rvalid=0,rready=1;
    reg [7:0] awaddr=0,araddr=0;reg [2:0] awprot=0,arprot=0;
    reg [31:0] wdata=0,rdata=0;reg [3:0] wstrb=15;reg [1:0] bresp=0,rresp=0;
    integer scenario,offset=1,checks=0;string wave;
    generate if(BUS==0) begin
        ahb_protocol_checker c(clk,rst_n,hsel,hready,hresp,hwrite,htrans,hsize,hburst,haddr,hwdata,hrdata);
    end else begin
        axi_lite_protocol_checker c(clk,rst_n,awvalid,awready,wvalid,wready,arvalid,arready,bvalid,bready,rvalid,rready,
            awaddr,araddr,awprot,arprot,wdata,rdata,wstrb,bresp,rresp);
    end endgenerate
    task cycle;begin @(posedge clk);#1;checks=checks+1;@(negedge clk);end endtask
    initial begin
        if(!$value$plusargs("SCENARIO=%d",scenario)) $fatal(1,"SCENARIO required");
        if($value$plusargs("OFFSET=%d",offset)) begin end
        if($value$plusargs("WAVE=%s",wave)) begin $dumpfile(wave);$dumpvars(0,checker_tb);end
        repeat(2) @(negedge clk);rst_n=1;
        if(BUS==0) case(scenario)
            1:begin hsel=1;htrans=2;cycle();hsel=0;htrans=0;hready=0;hresp=1;cycle();hready=1;hresp=0;cycle();end
            2:begin hsel=1;htrans=2;cycle();hready=0;haddr=4;cycle();haddr=8;cycle();end
            3:begin hsel=1;htrans=2;hwrite=1;cycle();hsel=0;htrans=0;hready=0;hwdata=1;cycle();hwdata=2;cycle();end
            4:begin hsel=1;htrans=2;cycle();hsel=0;htrans=0;hrdata='x;cycle();end
            5:begin haddr='x;hsize='x;hwrite='x;hwdata='x;hrdata='x;cycle();cycle();end
            6:begin
                hsel=1;htrans=2;hwrite=1;cycle();hsel=0;htrans=0;hready=0;cycle();
                #offset;rst_n=0;#1;rst_n=1;hready=1;hwdata=2;cycle();
            end
            7:begin hsel=1;htrans=2;cycle();hsel=0;htrans=0;hresp=1;cycle();end
            default:$fatal(1,"bad scenario");
        endcase
        else case(scenario)
            1:begin awready=0;awvalid=1;cycle();awaddr=4;cycle();end
            2:begin wready=0;wvalid=1;cycle();wdata=4;cycle();end
            3:begin arready=0;arvalid=1;cycle();araddr=4;cycle();end
            4:begin awvalid=1;wvalid=1;cycle();awvalid=0;wvalid=0;bvalid=1;bready=0;cycle();bvalid=0;cycle();end
            5:begin arvalid=1;cycle();arvalid=0;rvalid=1;rready=0;cycle();rdata=4;cycle();end
            6:begin bvalid=1;cycle();end
            7:begin awvalid=1;awaddr='x;cycle();end
            8:begin awaddr='x;wdata='x;wstrb='x;araddr='x;rdata='x;cycle();cycle();end
            10:begin awvalid=1;cycle();cycle();end
            11:begin rvalid=1;cycle();end
            9:begin awvalid=1;cycle();awvalid=0;#offset;rst_n=0;#1;rst_n=1;cycle();end
            default:$fatal(1,"bad scenario");
        endcase
        repeat(2) cycle();
        $display("RESULT PASS checks=%0d",checks);$finish;
    end
endmodule
