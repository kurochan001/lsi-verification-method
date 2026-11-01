// APB control + AXI4 INCR DMA + two-line image IP. One 8-bit pixel per 32-bit slot.
module image_dma #(parameter W=5,H=5,WAIT_CYCLES=0,MUTATION=0)(
    input wire clk,rst_n,psel,penable,pwrite,input wire [7:0] paddr,input wire [31:0] pwdata,
    output wire pready,pslverr,output reg [31:0] prdata,output wire irq,
    output wire arvalid,output wire [31:0] araddr,output wire [7:0] arlen,
    output wire [2:0] arsize,output wire [1:0] arburst,arid,input wire arready,
    input wire rvalid,input wire [31:0] rdata,input wire [1:0] rid,rresp,input wire rlast,output wire rready,
    output wire awvalid,output wire [31:0] awaddr,output wire [7:0] awlen,
    output wire [2:0] awsize,output wire [1:0] awburst,awid,input wire awready,
    output wire wvalid,output wire [31:0] wdata,output wire [3:0] wstrb,output wire wlast,input wire wready,
    input wire bvalid,input wire [1:0] bid,bresp,output wire bready,
    output reg busy,done,error
);
    localparam N=W*H,COLLECT=0,ADDRESS=1,DATA=2,RESPONSE=3;
    // The high three bytes of an input slot are padding, not image samples.
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_padding=&{1'b0,rdata[31:8]};
    /* verilator lint_on UNUSEDSIGNAL */
    reg [31:0] source,destination;
    reg irq_enable,read_active,error_seen,tx_final;
    reg [7:0] read_length,read_beat;
    integer wait_left,issued,received,written,fill,tx_count,tx_beat;
    reg [1:0] tx_state;
    reg [7:0] buffer[0:3];
    wire [32:0] source_end={1'b0,source}+33'(4*N),destination_end={1'b0,destination}+33'(4*N);
    wire bad_config=source[1:0]!=0 || destination[1:0]!=0 || source<32'h1000 || destination<32'h1000 ||
                    source_end>33'h2000 || destination_end>33'h2000 ||
                    !((source_end<={1'b0,destination}) || (destination_end<={1'b0,source}));
    wire known=paddr==0 || paddr==4 || paddr==8 || paddr==12 || paddr==16 || paddr==20;
    wire illegal_write=pwrite && (paddr==20 || (busy && paddr!=4));
    assign pready=psel && penable && wait_left==0;
    assign pslverr=pready && (!known || illegal_write);
    assign irq=irq_enable && (done || error);
    always @* case(paddr)
        0:prdata=0;
        4:prdata={29'd0,error,done,busy};
        8:prdata=source;
        12:prdata=destination;
        16:prdata={31'd0,irq_enable};
        20:prdata=(32'(H)<<16)|32'(W);
        default:prdata=0;
    endcase
    assign arvalid=busy && !read_active && issued<N;
    assign araddr=source+32'(issued*4);
    assign arlen=8'((N-issued>=4 ? 4 : N-issued)-1);
    assign arsize=3'd2;assign arburst=2'b01;assign arid=0;
    wire input_ready,pixel_valid,pixel_ready,pixel_last;
    wire [7:0] pixel;
    assign rready=busy && input_ready;
    assign pixel_ready=busy && tx_state==COLLECT && fill<4;
    wire filter_reset=rst_n && busy;
    sobel_stream #(.W(W),.H(H),.MUTATION(MUTATION==3 ? 1 : 0)) filter(
        .clk(clk),.rst_n(filter_reset),.in_valid(busy && rvalid),.in_pixel(rdata[7:0]),.in_ready(input_ready),
        .out_valid(pixel_valid),.out_ready(pixel_ready),.out_pixel(pixel),.out_last(pixel_last));
    assign awvalid=tx_state==ADDRESS;
    assign awaddr=destination+32'(written*4);assign awlen=8'(tx_count-1);
    assign awsize=3'd2;assign awburst=2'b01;assign awid=0;
    assign wvalid=tx_state==DATA;assign wdata={24'd0,buffer[tx_beat]};assign wstrb=4'b0001;
    assign wlast=tx_beat==tx_count-1;
    assign bready=tx_state==RESPONSE;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            source<=32'h1000;destination<=32'h1400;irq_enable<=0;busy<=0;done<=0;error<=0;
            read_active<=0;error_seen<=0;tx_final<=0;read_length<=0;read_beat<=0;
            wait_left<=0;issued<=0;received<=0;written<=0;fill<=0;tx_count<=0;tx_beat<=0;tx_state<=COLLECT;
            for(integer i=0;i<4;i=i+1)buffer[i]<=0;
        end else begin
            if(psel && !penable)wait_left<=WAIT_CYCLES;
            else if(psel && penable && wait_left!=0)wait_left<=wait_left-1;
            if(psel && penable && pready && !pslverr && pwrite)case(paddr)
                0:if(pwdata[0])begin
                    done<=0;error<=bad_config;
                    if(!bad_config)begin
                        busy<=1;error_seen<=0;read_active<=0;issued<=0;received<=0;written<=0;
                        fill<=0;tx_count<=0;tx_beat<=0;tx_state<=COLLECT;tx_final<=0;read_beat<=0;
                    end
                end
                4:begin if(pwdata[1])done<=0;if(pwdata[2])error<=0;end
                8:source<=pwdata;
                12:destination<=pwdata;
                16:irq_enable<=pwdata[0];
                default:;
            endcase
            if(arvalid && arready)begin
                read_active<=1;read_length<=arlen;read_beat<=0;issued<=issued+int'(arlen)+1;
            end
            if(rvalid && rready)begin
                received<=received+1;
                if(rresp!=0 || rid!=0 || rlast!=(read_beat==read_length))error_seen<=1;
                if(read_beat==read_length)read_active<=0;else read_beat<=read_beat+1'b1;
            end
            if(pixel_valid && pixel_ready)begin
                buffer[fill]<=pixel;fill<=fill+1;
                if(fill==3 || pixel_last)begin tx_count<=fill+1;tx_final<=pixel_last;tx_beat<=0;tx_state<=ADDRESS;end
            end
            if(awvalid && awready)tx_state<=DATA;
            if(wvalid && wready)begin
                if(wlast)begin
                    tx_state<=RESPONSE;
                    if(MUTATION==4 && tx_final)begin busy<=0;done<=1;end
                end else tx_beat<=tx_beat+1;
            end
            if(bvalid && bready)begin
                written<=written+tx_count;fill<=0;tx_state<=COLLECT;
                if(tx_final)begin
                    busy<=0;error<=error_seen || bresp!=0 || bid!=0 || received!=N;
                    done<=!error_seen && bresp==0 && bid==0 && received==N;
                end else if(bresp!=0 || bid!=0)error_seen<=1;
            end
        end
    end
endmodule
