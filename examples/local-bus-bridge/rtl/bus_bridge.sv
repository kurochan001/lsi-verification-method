`timescale 1ns/1ps
// Transaction-to-APB3 core: one request, two 256-byte windows, no byte strobes.
module transaction_apb #(parameter MUTATION=0)(
    input wire clk,rst_n,req_valid,req_write,req_bad,req_noop,rsp_ready,
    input wire [9:0] req_addr,input wire [31:0] req_data,
    output wire req_ready,output reg rsp_valid,rsp_error,output reg [31:0] rsp_data,
    output wire [1:0] psel,output wire penable,pwrite,output wire [7:0] paddr,output wire [31:0] pwdata,
    input wire pready,pslverr,input wire [31:0] prdata
);
    localparam IDLE=0,SETUP=1,ACCESS=2;
    reg [1:0] state;reg target,write_saved;reg [7:0] address_saved;reg [31:0] data_saved;
    assign req_ready=rst_n && state==IDLE && !rsp_valid;
    assign psel=rst_n && state!=IDLE ? ((target ^ (MUTATION==1)) ? 2'b10 : 2'b01) : 0;
    assign penable=state==ACCESS || (MUTATION==4 && state==SETUP);
    assign paddr=address_saved;assign pwrite=write_saved;
    assign pwdata=data_saved ^ (MUTATION==3 ? 32'h00000001 : 0);
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=IDLE;rsp_valid<=0;rsp_error<=0;rsp_data<=0;
            target<=0;write_saved<=0;address_saved<=0;data_saved<=0;
        end else begin
            if(rsp_valid && rsp_ready) rsp_valid<=0;
            if(req_valid && req_ready) begin
                target<=req_addr[8];address_saved<=req_addr[7:0];write_saved<=req_write;data_saved<=req_data;
                if(req_addr[9] || req_addr[1:0]!=0 || req_bad || req_noop) begin
                    rsp_valid<=1;rsp_error<=req_addr[9] || req_addr[1:0]!=0 || req_bad;rsp_data<=0;
                end else state<=SETUP;
            end
            if(state==SETUP) state<=ACCESS;
            if(state==ACCESS && pready) begin
                state<=IDLE;rsp_valid<=1;rsp_error<=pslverr && MUTATION!=2;
                rsp_data<=write_saved ? 0 : prdata;
            end
        end
    end
endmodule

module bus_bridge #(parameter BUS=0,WAIT_CYCLES=0,MUTATION=0)(
    input wire clk,rst_n,hsel,hwrite,input wire [1:0] htrans,input wire [9:0] haddr,
    input wire [2:0] hsize,input wire [31:0] hwdata,
    output wire hready,hresp,output wire [31:0] hrdata,
    input wire awvalid,wvalid,arvalid,bready,rready,input wire [9:0] awaddr,araddr,
    input wire [31:0] wdata,input wire [3:0] wstrb,
    output wire awready,wready,arready,bvalid,rvalid,output wire [1:0] bresp,rresp,output wire [31:0] rdata,
    output wire [1:0] psel,output wire penable,pwrite,output wire [7:0] paddr,output wire [31:0] pwdata,
    output wire apb_ready,apb_error,output wire [31:0] apb_data,
    output wire irq,watchdog_reset_request,timer_expired,output wire [3:0] timer_count,watchdog_count
);
    wire req_valid,req_ready,req_write,req_bad,req_noop,rsp_valid,rsp_ready,rsp_error;
    wire [9:0] req_addr;wire [31:0] req_data,rsp_data;
    generate if(BUS==0) begin: ahb_front
        reg active,write_saved,launched,error_second;reg [9:0] address_saved;reg [2:0] size_saved;
        assign req_valid=active && !launched;assign req_addr=address_saved;assign req_write=write_saved;
        assign req_data=hwdata;assign req_bad=size_saved!=2;assign req_noop=0;
        assign hready=!active || (rsp_valid && (!rsp_error || error_second));
        assign hresp=active && rsp_valid && rsp_error;assign hrdata=rsp_data;
        assign rsp_ready=active && hready;
        assign awready=0;assign wready=0;assign arready=0;assign bvalid=0;assign rvalid=0;
        assign bresp=0;assign rresp=0;assign rdata=0;
        always @(posedge clk or negedge rst_n) begin
            if(!rst_n) begin active<=0;write_saved<=0;launched<=0;error_second<=0;address_saved<=0;size_saved<=2;end
            else begin
                if(req_valid && req_ready) launched<=1;
                if(active && rsp_valid && rsp_error && !error_second) error_second<=1;
                if(active && hready) begin active<=0;launched<=0;error_second<=0;end
                if(hready && hsel && htrans[1]) begin active<=1;address_saved<=haddr;write_saved<=hwrite;size_saved<=hsize;launched<=0;error_second<=0;end
            end
        end
    end else begin: axi_front
        reg aw_full,w_full,ar_full,write_inflight,read_inflight,owner_write,bv,rv;
        reg [9:0] aw_saved,ar_saved;reg [31:0] data_saved,read_saved;reg [3:0] strobe_saved;reg [1:0] bp,rp;
        wire choose_write=aw_full && w_full && !write_inflight && !bv;
        wire choose_read=ar_full && !read_inflight && !rv && !choose_write;
        assign awready=rst_n && !aw_full && !write_inflight && !bv;
        assign wready=rst_n && !w_full && !write_inflight && !bv;
        assign arready=rst_n && !ar_full && !read_inflight && !rv;
        assign req_valid=choose_write || choose_read;assign req_write=choose_write;
        assign req_addr=choose_write ? aw_saved : ar_saved;assign req_data=data_saved;
        assign req_bad=choose_write && strobe_saved!=0 && strobe_saved!=15;
        assign req_noop=choose_write && strobe_saved==0;
        assign rsp_ready=owner_write ? !bv : !rv;
        assign bvalid=bv;assign rvalid=rv;assign bresp=bp;assign rresp=rp;assign rdata=read_saved;
        assign hready=1;assign hresp=0;assign hrdata=0;
        always @(posedge clk or negedge rst_n) begin
            if(!rst_n) begin
                aw_full<=0;w_full<=0;ar_full<=0;write_inflight<=0;read_inflight<=0;owner_write<=0;bv<=0;rv<=0;
                aw_saved<=0;ar_saved<=0;data_saved<=0;read_saved<=0;strobe_saved<=0;bp<=0;rp<=0;
            end else begin
                if(awvalid && awready) begin aw_full<=1;aw_saved<=awaddr;end
                if(wvalid && wready) begin w_full<=1;data_saved<=wdata;strobe_saved<=wstrb;end
                if(arvalid && arready) begin ar_full<=1;ar_saved<=araddr;end
                if(bv && bready) bv<=0;
                if(rv && rready) rv<=0;
                if(req_valid && req_ready) begin
                    owner_write<=choose_write;
                    if(choose_write) begin aw_full<=0;w_full<=0;write_inflight<=1;end
                    else begin ar_full<=0;read_inflight<=1;end
                end
                if(rsp_valid && rsp_ready) begin
                    if(owner_write) begin bv<=1;bp<=rsp_error ? 2 : 0;write_inflight<=0;end
                    else begin rv<=1;rp<=rsp_error ? 2 : 0;read_saved<=rsp_data;read_inflight<=0;end
                end
            end
        end
    end endgenerate
    transaction_apb #(.MUTATION(MUTATION)) core(clk,rst_n,req_valid,req_write,req_bad,req_noop,rsp_ready,req_addr,req_data,
        req_ready,rsp_valid,rsp_error,rsp_data,psel,penable,pwrite,paddr,pwdata,apb_ready,apb_error,apb_data);
    wire ready0,error0,ready1,error1;wire [31:0] data0,data1,config_value;wire [3:0] pending;
    apb_regs #(.WAIT_CYCLES(WAIT_CYCLES)) basic(clk,rst_n,psel[0],penable,pwrite,paddr,pwdata,4'b0000,ready0,error0,data0,config_value,pending);
    apb_timer #(.WIDTH(4),.WAIT_CYCLES(WAIT_CYCLES)) timer(clk,rst_n,psel[1],penable,pwrite,paddr,pwdata,ready1,error1,data1,
        irq,watchdog_reset_request,timer_expired,timer_count,watchdog_count);
    assign apb_ready=psel[1] ? ready1 : ready0;assign apb_error=psel[1] ? error1 : error0;assign apb_data=psel[1] ? data1 : data0;
endmodule
