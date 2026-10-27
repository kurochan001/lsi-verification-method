`timescale 1ns/1ps
// Port-only AHB-Lite contract. No DUT internal signals or fixed response latency.
module ahb_protocol_checker #(parameter ADDR_WIDTH=10)(
    input wire clk,rst_n,hsel,hready,hresp,hwrite,
    input wire [1:0] htrans,
    input wire [2:0] hsize,hburst,
    input wire [ADDR_WIDTH-1:0] haddr,
    input wire [31:0] hwdata,hrdata
);
    reg active=0,data_write=0;
    reg addr_wait=0,data_wait=0,error_first=0;
    reg [ADDR_WIDTH+9:0] old_address;
    reg [31:0] old_data;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label);$fatal(1,"AHB protocol checker");end
    endtask
`ifdef NATIVE_SVA
    reg [31:0] reset_epoch=0;
    always @(negedge rst_n) reset_epoch<=reset_epoch+1'b1;
    ap_address_hold: assert property (@(posedge clk) disable iff(!rst_n)
        (hsel && htrans[1] && !hready && !hresp) |=> ($changed(reset_epoch) || $stable({hsel,htrans,haddr,hwrite,hsize,hburst})))
        else fail("PROTO_AHB_ADDRESS");
    ap_data_hold: assert property (@(posedge clk) disable iff(!rst_n)
        (active && data_write && !hready) |=> ($changed(reset_epoch) || $stable(hwdata))) else fail("PROTO_AHB_DATA");
    ap_error_pair: assert property (@(posedge clk) disable iff(!rst_n)
        (active && hresp && !hready) |=> ($changed(reset_epoch) || (hresp && hready))) else fail("PROTO_AHB_ERROR");
    ap_error_start: assert property (@(posedge clk) disable iff(!rst_n)
        (active && hresp && hready) |-> error_first) else fail("PROTO_AHB_ERROR");
    cp_address_wait: cover property (@(posedge clk) rst_n && hsel && htrans[1] && !hready && !hresp);
    cp_error: cover property (@(posedge clk) rst_n && active && hresp && !hready);
    cp_pipeline: cover property (@(posedge clk) rst_n && active && hready && hsel && htrans[1]);
`endif
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin active<=0;data_write<=0;addr_wait<=0;data_wait<=0;error_first<=0;end
        else begin
            if((^{hsel,hready,hresp})===1'bx) fail("PROTO_AHB_X");
            if(hsel && (^{htrans})===1'bx) fail("PROTO_AHB_X");
            if(hsel && htrans[1] && (^{haddr,hsize,hburst,hwrite})===1'bx) fail("PROTO_AHB_X");
            if(active && data_write && (^hwdata)===1'bx) fail("PROTO_AHB_X");
            if(active && !data_write && hready && !hresp && (^hrdata)===1'bx) fail("PROTO_AHB_X");
`ifndef NATIVE_SVA
            if(addr_wait && {hsel,htrans,haddr,hwrite,hsize,hburst}!==old_address) fail("PROTO_AHB_ADDRESS");
            if(data_wait && hwdata!==old_data) fail("PROTO_AHB_DATA");
            if(active && hresp && hready && !error_first) fail("PROTO_AHB_ERROR");
            if(error_first && (!hresp || !hready)) fail("PROTO_AHB_ERROR");
`endif
            addr_wait<=hsel && htrans[1] && !hready && !hresp;
            old_address<={hsel,htrans,haddr,hwrite,hsize,hburst};
            data_wait<=active && data_write && !hready;old_data<=hwdata;
            error_first<=active && hresp && !hready;
            if(hready) begin active<=hsel && htrans[1];data_write<=hwrite;end
        end
    end
endmodule
