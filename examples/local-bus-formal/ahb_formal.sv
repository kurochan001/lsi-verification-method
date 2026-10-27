// Single-clock, sampled-reset formal contract for the existing AHB-Lite RTL.
module ahb_formal #(parameter WAIT_CYCLES=0,MUTATION=0,CHECK_DATA=0,LOCK_RESET=0)(
    input wire clk,rst_n,hsel,hwrite,
    input wire [1:0] htrans,
    input wire [2:0] hsize,hburst,
    input wire [9:0] haddr,
    input wire [31:0] hwdata
);
    wire hreadyout,hresp;wire [31:0] hrdata;
    ahb_regs #(.WAIT_CYCLES(WAIT_CYCLES),.MUTATION(MUTATION)) dut(
        .hclk(clk),.hresetn(rst_n),.hsel(hsel),.hready(hreadyout),.hwrite(hwrite),
        .htrans(htrans),.hsize(hsize),.hburst(hburst),.haddr(haddr),.hwdata(hwdata),
        .hreadyout(hreadyout),.hresp(hresp),.hrdata(hrdata));
    reg past_valid=0,active;
    reg [9:0] address;
    reg [2:0] size;
    reg write,bad;
    reg [$clog2(WAIT_CYCLES+3)-1:0] age;
    (* anyconst *) reg [1:0] watched_index;
    reg [31:0] watched_word;
    reg recovering=0;
    wire expected_ready=!rst_n || !active || age>=WAIT_CYCLES+(bad ? 1 : 0);
    wire expected_resp=rst_n && active && bad && age>=WAIT_CYCLES;
    wire accept=rst_n && expected_ready && hsel && htrans[1];
    wire finish=rst_n && active && expected_ready;
    wire [9:0] base={address[9:2],2'b00};
    wire [31:0] expected_data=address>=16 ? 32'h4148424c :
        watched_word;
    always @(posedge clk) begin
        past_valid<=1;
        if(!past_valid) as_initial_reset: assume(!rst_n);
        if(past_valid && rst_n && $past(rst_n)) begin
            if($past(!hreadyout && !hresp && hsel && htrans[1]))
                as_hold_address: assume({hsel,htrans,haddr,hwrite,hsize,hburst}==
                                       $past({hsel,htrans,haddr,hwrite,hsize,hburst}));
            if($past(active && write && !hreadyout)) as_hold_data: assume(hwdata==$past(hwdata));
        end
        if(!rst_n) begin
            active<=0;address<=0;size<=0;write<=0;bad<=0;age<=0;
            watched_word<=0;
            if(past_valid && active) recovering<=1;
        end else begin
            if(active && !expected_ready) age<=age+1'b1;
            if(finish) begin
                active<=0;age<=0;
                if(write && !bad && address[3:2]==watched_index)
                    for(integer lane=0;lane<4;lane=lane+1)
                        if(lane>=address[1:0] && lane<address[1:0]+(1<<size))
                            watched_word[8*lane+:8]<=hwdata[8*lane+:8];
            end
            if(accept) begin
                active<=1;address<=haddr;size<=hsize;write<=hwrite;age<=0;
                bad<=hsize>2 || (haddr & ((1<<hsize)-1))!=0 || haddr>=20 || (hwrite && haddr>=16);
            end
            if(recovering && finish && !write && !bad) recovering<=0;
        end
        if(past_valid) begin
            ap_response: assert(hreadyout==expected_ready && hresp==expected_resp);
            if(!rst_n) ap_reset: assert(hreadyout && !hresp);
            if(rst_n && $past(rst_n && hresp && !hreadyout))
                ap_error_pair: assert(hresp && hreadyout);
            cp_write: cover(finish && write && !bad);
            cp_read: cover(finish && !write && !bad);
            cp_pipeline: cover(finish && accept);
            cp_error_first: cover(rst_n && hresp && !hreadyout);
            cp_error: cover(finish && hresp);
            cp_subword: cover(finish && write && !bad && size<2);
            cp_reset_pending: cover(!rst_n && active);
            cp_recovery: cover(rst_n && recovering && finish && !write && !bad);
        end
    end
    generate if(CHECK_DATA) begin: data_checks
        always @(posedge clk) if(past_valid && finish && !write && !bad &&
            (address>=16 || address[3:2]==watched_index)) ap_data: assert(hrdata==expected_data);
    end endgenerate
    generate if(LOCK_RESET) begin: locked_reset
        always @(posedge clk) as_lock_reset: assume(!rst_n);
    end endgenerate
endmodule
