`timescale 1ns/1ps
// Independent Lite channel accounting. MAX_OUTSTANDING is the integration contract.
module axi_lite_protocol_checker #(parameter ADDR_WIDTH=8,MAX_OUTSTANDING=1)(
    input wire clk,rst_n,awvalid,awready,wvalid,wready,arvalid,arready,bvalid,bready,rvalid,rready,
    input wire [ADDR_WIDTH-1:0] awaddr,araddr,
    input wire [2:0] awprot,arprot,
    input wire [31:0] wdata,rdata,
    input wire [3:0] wstrb,
    input wire [1:0] bresp,rresp
);
    integer aw_credit=0,w_credit=0,ar_credit=0;
    reg aw_wait=0,w_wait=0,ar_wait=0,b_wait=0,r_wait=0;
    reg [ADDR_WIDTH+2:0] old_aw,old_ar;
    reg [35:0] old_w;reg [33:0] old_r;reg [1:0] old_b;
    task fail(input string label);
        begin $display("CHECK_FAIL %s",label);$fatal(1,"AXI-Lite protocol checker");end
    endtask
`ifdef NATIVE_SVA
    reg [31:0] reset_epoch=0;
    always @(negedge rst_n) reset_epoch<=reset_epoch+1'b1;
    ap_aw_hold: assert property (@(posedge clk) disable iff(!rst_n)
        (awvalid && !awready) |=> ($changed(reset_epoch) || (awvalid && $stable({awaddr,awprot})))) else fail("PROTO_AXI_AW");
    ap_w_hold: assert property (@(posedge clk) disable iff(!rst_n)
        (wvalid && !wready) |=> ($changed(reset_epoch) || (wvalid && $stable({wdata,wstrb})))) else fail("PROTO_AXI_W");
    ap_ar_hold: assert property (@(posedge clk) disable iff(!rst_n)
        (arvalid && !arready) |=> ($changed(reset_epoch) || (arvalid && $stable({araddr,arprot})))) else fail("PROTO_AXI_AR");
    ap_b_hold: assert property (@(posedge clk) disable iff(!rst_n)
        (bvalid && !bready) |=> ($changed(reset_epoch) || (bvalid && $stable(bresp)))) else fail("PROTO_AXI_B");
    ap_r_hold: assert property (@(posedge clk) disable iff(!rst_n)
        (rvalid && !rready) |=> ($changed(reset_epoch) || (rvalid && $stable({rdata,rresp})))) else fail("PROTO_AXI_R");
    ap_b_cause: assert property (@(posedge clk) disable iff(!rst_n)
        bvalid |-> (aw_credit>0 && w_credit>0)) else fail("PROTO_AXI_CAUSALITY");
    ap_r_cause: assert property (@(posedge clk) disable iff(!rst_n)
        rvalid |-> ar_credit>0) else fail("PROTO_AXI_CAUSALITY");
    cp_aw_wait: cover property (@(posedge clk) rst_n && awvalid && !awready);
    cp_w_wait: cover property (@(posedge clk) rst_n && wvalid && !wready);
    cp_ar_wait: cover property (@(posedge clk) rst_n && arvalid && !arready);
    cp_b_wait: cover property (@(posedge clk) rst_n && bvalid && !bready);
    cp_r_wait: cover property (@(posedge clk) rst_n && rvalid && !rready);
`endif
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            aw_credit<=0;w_credit<=0;ar_credit<=0;
            aw_wait<=0;w_wait<=0;ar_wait<=0;b_wait<=0;r_wait<=0;
        end else begin
            if((^{awvalid,awready,wvalid,wready,arvalid,arready,bvalid,bready,rvalid,rready})===1'bx) fail("PROTO_AXI_X");
            if(awvalid && (^{awaddr,awprot})===1'bx) fail("PROTO_AXI_X");
            if(wvalid && (^{wdata,wstrb})===1'bx) fail("PROTO_AXI_X");
            if(arvalid && (^{araddr,arprot})===1'bx) fail("PROTO_AXI_X");
            if(bvalid && (^bresp)===1'bx) fail("PROTO_AXI_X");
            if(rvalid && (^{rdata,rresp})===1'bx) fail("PROTO_AXI_X");
`ifndef NATIVE_SVA
            if(aw_wait && (!awvalid || {awaddr,awprot}!==old_aw)) fail("PROTO_AXI_AW");
            if(w_wait && (!wvalid || {wdata,wstrb}!==old_w)) fail("PROTO_AXI_W");
            if(ar_wait && (!arvalid || {araddr,arprot}!==old_ar)) fail("PROTO_AXI_AR");
            if(b_wait && (!bvalid || bresp!==old_b)) fail("PROTO_AXI_B");
            if(r_wait && (!rvalid || {rdata,rresp}!==old_r)) fail("PROTO_AXI_R");
            if(bvalid && (aw_credit<=0 || w_credit<=0)) fail("PROTO_AXI_CAUSALITY");
            if(rvalid && ar_credit<=0) fail("PROTO_AXI_CAUSALITY");
`endif
            aw_credit<=aw_credit+int'(awvalid && awready)-int'(bvalid && bready);
            w_credit<=w_credit+int'(wvalid && wready)-int'(bvalid && bready);
            ar_credit<=ar_credit+int'(arvalid && arready)-int'(rvalid && rready);
            if(aw_credit+int'(awvalid && awready)-int'(bvalid && bready)<0 ||
               aw_credit+int'(awvalid && awready)-int'(bvalid && bready)>MAX_OUTSTANDING ||
               w_credit+int'(wvalid && wready)-int'(bvalid && bready)<0 ||
               w_credit+int'(wvalid && wready)-int'(bvalid && bready)>MAX_OUTSTANDING ||
               ar_credit+int'(arvalid && arready)-int'(rvalid && rready)<0 ||
               ar_credit+int'(arvalid && arready)-int'(rvalid && rready)>MAX_OUTSTANDING) fail("PROTO_AXI_CREDIT");
            aw_wait<=awvalid && !awready;old_aw<={awaddr,awprot};
            w_wait<=wvalid && !wready;old_w<={wdata,wstrb};
            ar_wait<=arvalid && !arready;old_ar<={araddr,arprot};
            b_wait<=bvalid && !bready;old_b<=bresp;
            r_wait<=rvalid && !rready;old_r<={rdata,rresp};
        end
    end
endmodule
