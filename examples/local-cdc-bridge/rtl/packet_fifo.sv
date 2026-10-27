// Adapted from local-async-fifo: wide packets and coordinated, locally released resets.
module packet_fifo #(parameter DEPTH=4, SYNC_STAGES=2, WIDTH=57, MUTATION=0)(
    input wire wclk,rclk,wrst_n,rrst_n,wr_en,rd_en,
    input wire [WIDTH-1:0] wr_data,
    output reg full,empty,rd_valid,
    output reg [WIDTH-1:0] rd_data
);
    localparam A=$clog2(DEPTH);
    reg [WIDTH-1:0] memory[0:DEPTH-1];
    reg [A:0] wbin,rbin,wgray,rgray;
    reg [A:0] rsync[0:SYNC_STAGES-1],wsync[0:SYNC_STAGES-1];
    wire write_ok=wr_en && !full;
    wire read_ok=rd_en && (!empty || MUTATION==3);
    wire [A:0] wn=wbin+write_ok, rn=rbin+read_ok;
    wire [A:0] wg=MUTATION==4 ? wn : (wn>>1)^wn;
    wire [A:0] rg=(rn>>1)^rn;
    wire [A:0] full_target=rsync[SYNC_STAGES-1] ^ ((1<<A)|(1<<(A-1)));
    always @(posedge wclk or negedge wrst_n) begin
        if(!wrst_n) begin
            wbin<=0;wgray<=0;full<=0;
            for(integer i=0;i<SYNC_STAGES;i=i+1) rsync[i]<=0;
        end else begin
            rsync[0]<=rgray;
            for(integer i=1;i<SYNC_STAGES;i=i+1) rsync[i]<=rsync[i-1];
            if(write_ok) memory[wbin[A-1:0]]<=wr_data;
            wbin<=wn;wgray<=wg;
            full<=MUTATION==2 ? 0 : wg==full_target;
        end
    end
    always @(posedge rclk or negedge rrst_n) begin
        if(!rrst_n) begin
            rbin<=0;rgray<=0;empty<=1;rd_valid<=0;rd_data<=0;
            for(integer i=0;i<SYNC_STAGES;i=i+1) wsync[i]<=0;
        end else begin
            wsync[0]<=wgray;
            for(integer i=1;i<SYNC_STAGES;i=i+1) wsync[i]<=wsync[i-1];
            rd_valid<=read_ok;
            if(read_ok) rd_data<=memory[rbin[A-1:0]] ^ (MUTATION==1 ? 8'h01 : 8'h00);
            rbin<=rn;rgray<=rg;
            empty<=rg==wsync[SYNC_STAGES-1];
        end
    end
endmodule
