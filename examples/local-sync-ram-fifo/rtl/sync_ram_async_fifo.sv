module sync_ram_async_fifo #(
    parameter integer WIDTH=32, DEPTH=8, READ_LATENCY=1, MUTATION=0,
    parameter integer AW=$clog2(DEPTH), PW=AW+1,
    parameter integer BUFFER=READ_LATENCY+2, BW=$clog2(BUFFER), CW=$clog2(BUFFER+1)
)(
    input wire wr_clk, rd_clk, arst_n,
    input wire wr_valid,
    output wire wr_ready,
    input wire [WIDTH-1:0] wr_data,
    output wire rd_valid,
    input wire rd_ready,
    output wire [WIDTH-1:0] rd_data
);
    wire wr_up, rd_up;
    memory_reset_sync wr_release(.clk(wr_clk),.arst_n(arst_n),.up(wr_up));
    memory_reset_sync rd_release(.clk(rd_clk),.arst_n(arst_n),.up(rd_up));
    (* ASYNC_REG="TRUE" *) reg [PW-1:0] rgray_w1,rgray_w2,wgray_r1,wgray_r2;
    (* ASYNC_REG="TRUE" *) reg [1:0] rd_alive,wr_alive;
    reg [PW-1:0] wbin,wgray,rbin,rgray,fetch_bin;
    reg full;
    wire wr_enabled=wr_up && rd_alive[1];
    wire rd_enabled=rd_up && wr_alive[1];
    wire push=wr_valid && wr_ready;
    wire pop=rd_valid && (rd_ready || MUTATION==2);
    wire [PW-1:0] wnext=wbin+PW'(push);
    wire [PW-1:0] wgray_next=(wnext>>1)^wnext;
    wire [PW-1:0] rnext=rbin+PW'(pop);
    wire [PW-1:0] fetch_gray=(fetch_bin>>1)^fetch_bin;
    reg [WIDTH-1:0] queue[0:BUFFER-1];
    reg [BW-1:0] head,tail;
    reg [CW-1:0] count,reserved;
    wire issue=rd_enabled && (fetch_gray!=wgray_r2) && (reserved<CW'(BUFFER) || pop);
    wire ram_valid;
    wire [WIDTH-1:0] ram_data;
    sync_dual_clock_ram #(.WIDTH(WIDTH),.DEPTH(DEPTH),.READ_LATENCY(READ_LATENCY)) ram(
        .wr_clk(wr_clk),.wr_enable(push),.wr_address(wbin[AW-1:0]),.wr_data(wr_data),
        .rd_clk(rd_clk),.arst_n(arst_n),.rd_enable(issue),.rd_address(fetch_bin[AW-1:0]),
        .rd_valid(ram_valid),.rd_data(ram_data));
    assign wr_ready=wr_enabled && (!full || MUTATION==4);
    assign rd_valid=rd_enabled && count!=0;
    assign rd_data=queue[head] ^ WIDTH'(MUTATION==1 ? 1:0);

    always @(posedge wr_clk or negedge arst_n)begin
        if(!arst_n)begin
            wbin<=0;wgray<=0;full<=0;rgray_w1<=0;rgray_w2<=0;rd_alive<=0;
        end else begin
            rgray_w1<=rgray;rgray_w2<=rgray_w1;rd_alive<={rd_alive[0],rd_up};
            wbin<=wnext;wgray<=wgray_next;
            full<=wgray_next=={~rgray_w2[PW-1:PW-2],rgray_w2[PW-3:0]};
        end
    end
    always @(posedge rd_clk or negedge arst_n)begin
        if(!arst_n)begin
            rbin<=0;rgray<=0;fetch_bin<=0;wgray_r1<=0;wgray_r2<=0;wr_alive<=0;
            head<=0;tail<=0;count<=0;reserved<=0;
        end else begin
            wgray_r1<=wgray;wgray_r2<=wgray_r1;wr_alive<={wr_alive[0],wr_up};
            rbin<=rnext;rgray<=(rnext>>1)^rnext;
            if(issue)fetch_bin<=fetch_bin+1'b1;
            if(ram_valid)begin
                queue[tail]<=MUTATION==3 ? '0 : ram_data;
                tail<=tail==BW'(BUFFER-1) ? '0 : tail+1'b1;
            end
            if(pop)head<=head==BW'(BUFFER-1) ? '0 : head+1'b1;
            case({ram_valid,pop})
                2'b10:count<=count+1'b1;
                2'b01:count<=count-1'b1;
                default:begin end
            endcase
            case({issue,pop})
                2'b10:reserved<=reserved+1'b1;
                2'b01:reserved<=reserved-1'b1;
                default:begin end
            endcase
        end
    end
endmodule
