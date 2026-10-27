// Independent one-entry transaction scoreboard; B/R receivers may stall forever.
module axi_formal #(parameter RESP_DELAY=0,MUTATION=0,CHECK_DATA=0,LOCK_RESET=0)(
    input wire clk,rst_n,awvalid,wvalid,arvalid,bready,rready,
    input wire [7:0] awaddr,araddr,
    input wire [2:0] awprot,arprot,
    input wire [31:0] wdata,
    input wire [3:0] wstrb
);
    wire awready,wready,arready,bvalid,rvalid;
    wire [1:0] bresp,rresp;wire [31:0] rdata;
    axi_lite_regs #(.RESP_DELAY(RESP_DELAY),.MUTATION(MUTATION)) dut(
        .aclk(clk),.aresetn(rst_n),.awvalid(awvalid),.wvalid(wvalid),.arvalid(arvalid),
        .bready(bready),.rready(rready),.awaddr(awaddr),.araddr(araddr),.awprot(awprot),.arprot(arprot),
        .wdata(wdata),.wstrb(wstrb),.awready(awready),.wready(wready),.arready(arready),
        .bvalid(bvalid),.rvalid(rvalid),.bresp(bresp),.rresp(rresp),.rdata(rdata));
    reg past_valid=0,aw_owed,w_owed,ar_owed,expected_bvalid,expected_rvalid;
    reg [7:0] write_address,read_address;
    reg [31:0] write_data,read_data;
    reg [3:0] write_strobe;
    reg [1:0] expected_bresp,expected_rresp;
    reg [$clog2(RESP_DELAY+3)-1:0] write_age,read_age;
    (* anyconst *) reg [1:0] watched_index;
    reg [31:0] watched_word;
    reg check_read_data;
    reg recovering=0;
    wire aw_accept=rst_n && awvalid && !aw_owed;
    wire w_accept=rst_n && wvalid && !w_owed;
    wire ar_accept=rst_n && arvalid && !ar_owed;
    wire commit=rst_n && aw_owed && w_owed && !expected_bvalid && write_age==RESP_DELAY;
    wire write_bad=write_address[1:0]!=0 || write_address>=16;
    wire read_bad=araddr[1:0]!=0 || araddr>16;
    wire [31:0] snapshot=read_bad ? 0 : araddr==16 ? 32'h4158494c :
                            watched_word;
    always @(posedge clk) begin
        past_valid<=1;
        if(!past_valid) as_initial_reset: assume(!rst_n);
        if(past_valid && rst_n && $past(rst_n)) begin
            if($past(awvalid && !awready)) as_aw_hold: assume(awvalid && {awaddr,awprot}==$past({awaddr,awprot}));
            if($past(wvalid && !wready)) as_w_hold: assume(wvalid && {wdata,wstrb}==$past({wdata,wstrb}));
            if($past(arvalid && !arready)) as_ar_hold: assume(arvalid && {araddr,arprot}==$past({araddr,arprot}));
        end
        if(!rst_n) begin
            aw_owed<=0;w_owed<=0;ar_owed<=0;expected_bvalid<=0;expected_rvalid<=0;
            write_address<=0;read_address<=0;write_data<=0;write_strobe<=0;read_data<=0;
            expected_bresp<=0;expected_rresp<=0;write_age<=0;read_age<=0;
            watched_word<=0;check_read_data<=0;
            if(past_valid && (aw_owed || w_owed || ar_owed)) recovering<=1;
        end else begin
            if(aw_accept) begin aw_owed<=1;write_address<=awaddr;end
            if(w_accept) begin w_owed<=1;write_data<=wdata;write_strobe<=wstrb;end
            if(expected_bvalid && bready) begin
                expected_bvalid<=0;aw_owed<=0;w_owed<=0;write_age<=0;
            end
            if(aw_owed && w_owed && !expected_bvalid) begin
                if(write_age==RESP_DELAY) begin
                    expected_bvalid<=1;expected_bresp<=write_bad ? 2 : 0;
                    if(!write_bad && write_address[3:2]==watched_index)
                        for(integer lane=0;lane<4;lane=lane+1)
                            if(write_strobe[lane]) watched_word[8*lane+:8]<=write_data[8*lane+:8];
                end else write_age<=write_age+1'b1;
            end
            if(ar_accept) begin
                ar_owed<=1;read_age<=0;read_data<=snapshot;read_address<=araddr;
                expected_rresp<=read_bad ? 2 : 0;
                check_read_data<=read_bad || araddr==16 || araddr[3:2]==watched_index;
            end
            if(ar_owed && !expected_rvalid) begin
                if(read_age==RESP_DELAY) expected_rvalid<=1;
                else read_age<=read_age+1'b1;
            end
            if(expected_rvalid && rready) begin expected_rvalid<=0;ar_owed<=0;read_age<=0;end
            if(recovering && expected_rvalid && rready) recovering<=0;
        end
        if(past_valid) begin
            if(rst_n) ai_reference_bounds: assert(write_age<=RESP_DELAY && read_age<=RESP_DELAY &&
                ((aw_owed && w_owed) || write_age==0) && (ar_owed || read_age==0));
            ap_ready: assert(awready==(rst_n && !aw_owed) && wready==(rst_n && !w_owed) && arready==(rst_n && !ar_owed));
            ap_valid: assert(bvalid==(rst_n && expected_bvalid) && rvalid==(rst_n && expected_rvalid));
            if(!rst_n) ap_reset: assert(!bvalid && !rvalid && !awready && !wready && !arready);
            if(rst_n && $past(rst_n && bvalid && !bready)) ap_b_hold: assert(bvalid && bresp==$past(bresp));
            if(rst_n && $past(rst_n && rvalid && !rready)) ap_r_hold: assert(rvalid && {rdata,rresp}==$past({rdata,rresp}));
            if(rst_n) ap_causality: assert((!bvalid || (aw_owed && w_owed)) && (!rvalid || ar_owed));
            cp_aw_first: cover(rst_n && aw_owed && !w_owed && w_accept);
            cp_w_first: cover(rst_n && w_owed && !aw_owed && aw_accept);
            cp_together: cover(aw_accept && w_accept);
            cp_b_stall: cover(rst_n && bvalid && !bready);
            cp_r_stall: cover(rst_n && rvalid && !rready);
            cp_strobe_zero: cover(w_accept && wstrb==0);
            cp_read_write: cover(ar_accept && (aw_accept || w_accept));
            cp_error: cover(rst_n && ((bvalid && bready && bresp==2) || (rvalid && rready && rresp==2)));
            cp_reset_partial: cover(!rst_n && (aw_owed ^ w_owed));
            cp_reset_response: cover(!rst_n && (expected_bvalid || expected_rvalid));
            cp_recovery: cover(rst_n && recovering && rvalid && rready);
            cp_snapshot: cover(rst_n && rvalid && !rready && commit && !write_bad && write_address==read_address);
        end
    end
    generate if(CHECK_DATA) begin: data_checks
        always @(posedge clk) if(past_valid && rst_n) ap_payload: assert(
            (!bvalid || bresp==expected_bresp) && (!rvalid || (rresp==expected_rresp && (!check_read_data || rdata==read_data))));
    end endgenerate
    generate if(LOCK_RESET) begin: locked_reset
        always @(posedge clk) as_lock_reset: assume(!rst_n);
    end endgenerate
endmodule
