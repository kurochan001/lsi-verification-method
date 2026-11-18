// Fall-through asynchronous-read memory; only complete packets cross domains.
// Gray pointers cross through two FFs. Flags are local and conservative.
module video_async_fifo #(parameter DATA_W=58,DEPTH=16)(
    input wire wclk,rclk,wr_reset_n,rd_reset_n,
    input wire wr_valid,output wire wr_ready,input wire [DATA_W-1:0] wr_data,
    output wire rd_valid,input wire rd_ready,output wire [DATA_W-1:0] rd_data,
    output wire [$clog2(DEPTH):0] read_level
);
    localparam A=$clog2(DEPTH);
    reg [DATA_W-1:0] memory[0:DEPTH-1];
    reg [A:0] wbin,rbin,wgray,rgray;
    (* ASYNC_REG = "TRUE" *) reg [A:0] rsync1,rsync2,wsync1,wsync2;
    reg full,empty;
    wire push=wr_valid && wr_ready, pop=rd_valid && rd_ready;
    wire [A:0] next_wbin=wbin+{{A{1'b0}},push};
    wire [A:0] next_rbin=rbin+{{A{1'b0}},pop};
    wire [A:0] next_wgray=(next_wbin>>1)^next_wbin;
    wire [A:0] next_rgray=(next_rbin>>1)^next_rbin;
    wire [A:0] full_target={~rsync2[A:A-1],rsync2[A-2:0]};
    function automatic [A:0] gray_to_bin(input [A:0] gray);
        reg [A:0] value;
        begin
            value[A]=gray[A];
            for (integer b=A-1;b>=0;b=b-1) value[b]=value[b+1]^gray[b];
            gray_to_bin=value;
        end
    endfunction
    assign wr_ready=wr_reset_n && !full;
    assign rd_valid=rd_reset_n && !empty;
    assign rd_data=rd_valid ? memory[rbin[A-1:0]] : {DATA_W{1'b0}};
    assign read_level=gray_to_bin(wsync2)-rbin;
    always @(posedge wclk or negedge wr_reset_n) begin
        if (!wr_reset_n) begin
            wbin<=0; wgray<=0; rsync1<=0; rsync2<=0; full<=0;
        end else begin
            rsync1<=rgray; rsync2<=rsync1;
            if (push) memory[wbin[A-1:0]]<=wr_data;
            wbin<=next_wbin; wgray<=next_wgray;
            full<=next_wgray==full_target;
        end
    end
    always @(posedge rclk or negedge rd_reset_n) begin
        if (!rd_reset_n) begin
            rbin<=0; rgray<=0; wsync1<=0; wsync2<=0; empty<=1;
        end else begin
            wsync1<=wgray; wsync2<=wsync1;
            rbin<=next_rbin; rgray<=next_rgray;
            empty<=next_rgray==wsync2;
        end
    end
endmodule
