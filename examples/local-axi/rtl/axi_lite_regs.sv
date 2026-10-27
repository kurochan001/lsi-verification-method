// Teaching AXI4-Lite register bank: separate AW/W slots and one response per direction.
module axi_lite_regs #(parameter RESP_DELAY=0,MUTATION=0)(
    input wire aclk,aresetn,awvalid,wvalid,arvalid,bready,rready,
    input wire [7:0] awaddr,araddr,
    input wire [2:0] awprot,arprot,
    input wire [31:0] wdata,
    input wire [3:0] wstrb,
    output wire awready,wready,arready,
    output reg bvalid,rvalid,
    output reg [1:0] bresp,rresp,
    output wire [31:0] rdata
);
    reg [31:0] registers[0:3];
    reg aw_full,w_full,write_pending,read_pending;
    reg [7:0] saved_awaddr,saved_araddr;
    reg [31:0] saved_wdata,saved_read,rdata_hold;
    reg [3:0] saved_wstrb;
    reg [1:0] saved_rresp;
    integer write_remaining,read_remaining;
    function automatic valid_address(input [7:0] address);
        valid_address=address[1:0]==0 && address<=16;
    endfunction
    function automatic [31:0] read_word(input [7:0] address);
        begin
            if(!valid_address(address)) read_word=0;
            else if(address==16) read_word=32'h4158494c;
            else read_word=registers[address[3:2]];
        end
    endfunction
    assign awready=aresetn && !aw_full && !write_pending && !bvalid;
    assign wready=aresetn && !w_full && !write_pending && !bvalid;
    assign arready=aresetn && !read_pending && !rvalid;
    wire [31:0] live_read=!valid_address(saved_araddr) ? 0 :
                          saved_araddr==16 ? 32'h4158494c : registers[saved_araddr[3:2]];
    assign rdata=(MUTATION==4 && rvalid && !rready) ? live_read : rdata_hold;
    wire commit_write=aw_full && w_full && !bvalid &&
                      ((RESP_DELAY==0 && !write_pending) || (write_pending && write_remaining==0));
    wire [31:0] commit_data=MUTATION==1 ? wdata : saved_wdata;
    always @(posedge aclk or negedge aresetn) begin
        if(!aresetn) begin
            aw_full<=0;w_full<=0;write_pending<=0;read_pending<=0;
            bvalid<=0;rvalid<=0;bresp<=0;rresp<=0;rdata_hold<=0;
            saved_awaddr<=0;saved_araddr<=0;saved_wdata<=0;saved_wstrb<=0;
            saved_read<=0;saved_rresp<=0;write_remaining<=0;read_remaining<=0;
            for(integer i=0;i<4;i=i+1) registers[i]<=0;
        end else begin
            if(bvalid && bready) bvalid<=0;
            if(rvalid && rready) rvalid<=0;
            if(awvalid && awready) begin aw_full<=1;saved_awaddr<=awaddr;end
            if(wvalid && wready) begin w_full<=1;saved_wdata<=wdata;saved_wstrb<=wstrb;end
            if(aw_full && w_full && !bvalid) begin
                if(commit_write) begin
                    bvalid<=1;aw_full<=0;w_full<=0;write_pending<=0;
                    bresp<=(!valid_address(saved_awaddr) || saved_awaddr==16) ? 2 : 0;
                    if(valid_address(saved_awaddr) && saved_awaddr!=16)
                        for(integer lane=0;lane<4;lane=lane+1)
                            if(saved_wstrb[lane] || MUTATION==2)
                                registers[saved_awaddr[3:2]][8*lane+:8]<=commit_data[8*lane+:8];
                end else if(!write_pending) begin
                    write_pending<=1;write_remaining<=RESP_DELAY-1;
                end else write_remaining<=write_remaining-1;
            end
            if(arvalid && arready) begin
                read_pending<=1;read_remaining<=RESP_DELAY;
                saved_araddr<=araddr;saved_read<=read_word(araddr);
                saved_rresp<=valid_address(araddr) ? 0 : 2;
            end else if(read_pending) begin
                if(read_remaining==0) begin
                    read_pending<=0;rvalid<=1;rdata_hold<=saved_read;rresp<=saved_rresp;
                end else read_remaining<=read_remaining-1;
            end
            if(MUTATION==3 && bvalid && !bready) bvalid<=0;
        end
    end
`ifdef FORMAL
    // Verified invariants strengthen induction; these do not constrain inputs.
    reg invariant_past_valid=0;
    always @(posedge aclk) begin
        invariant_past_valid<=1;
        if(invariant_past_valid && aresetn) begin
            ai_read_exclusive: assert(!(read_pending && rvalid));
            ai_read_bounds: assert(read_remaining>=0 && read_remaining<=RESP_DELAY);
            ai_write_bounds: assert(write_remaining>=0 && write_remaining<=(RESP_DELAY>0 ? RESP_DELAY-1 : 0));
            ai_write_state: assert((!write_pending || (aw_full && w_full && !bvalid)) &&
                (!bvalid || (!aw_full && !w_full && !write_pending)));
        end
    end
`endif
endmodule
