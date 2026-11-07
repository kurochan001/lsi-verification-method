// Bounded NIC: unstoppable byte RX, two-frame queue, software-owned DMA buffer.
// AXI4 INCR single-beat transfers, one outstanding per direction, byte-per-word RAM.
module network_nic #(parameter MAX_FRAME=128,WAIT_CYCLES=1,MUTATION=0)(
    input wire clk,rst_n,rx_valid,rx_last,rx_error,input wire [7:0] rx_data,
    output wire tx_valid,tx_last,output wire [7:0] tx_data,input wire tx_ready,
    input wire psel,penable,pwrite,input wire [7:0] paddr,input wire [31:0] pwdata,
    output wire pready,pslverr,output reg [31:0] prdata,output wire irq,
    output wire arvalid,output wire [31:0] araddr,output wire [7:0] arlen,output wire [2:0] arsize,
    output wire [1:0] arburst,arid,input wire arready,rvalid,rlast,input wire [31:0] rdata,input wire [1:0] rid,rresp,output wire rready,
    output wire awvalid,output wire [31:0] awaddr,output wire [7:0] awlen,output wire [2:0] awsize,
    output wire [1:0] awburst,awid,input wire awready,
    output wire wvalid,output wire [31:0] wdata,output wire [3:0] wstrb,output wire wlast,input wire wready,
    input wire bvalid,input wire [1:0] bid,bresp,output wire bready
);
    localparam IDLE=0,ADDRESS=1,DATA=2,RESPONSE=3,SEND=4;
    reg run,rx_owned;reg [3:0] status,mask;
    reg [31:0] rx_ptr,tx_ptr,tx_length,drop_count,rx_count,tx_count,last_error;
    reg [15:0] rx_length;reg [1:0] rx_kind;
    reg [2:0] rx_state,tx_state;
    reg [15:0] ri,ti;reg rx_bad,tx_bad;
    reg [8*MAX_FRAME-1:0] rx_copy,tx_copy;
    integer wait_count;
    wire frame_valid,frame_ready,frame_error,accept;
    wire [8*MAX_FRAME-1:0] frame_data;
    wire [15:0] frame_length,reply_length;
    wire [1:0] kind,occupancy;wire [3:0] drop_reason;
    wire [31:0] accepted,full_drops,long_drops;
    wire [8*MAX_FRAME-1:0] reply_data;
    rx_frame_queue #(.MAX_FRAME(MAX_FRAME)) queue(.clk(clk),.rst_n(rst_n),.rx_valid(rx_valid&&run),.rx_last(rx_last),.rx_error(rx_error),.rx_data(rx_data),
        .frame_valid(frame_valid),.frame_ready(frame_ready),.frame_error(frame_error),.frame_data(frame_data),.frame_length(frame_length),
        .occupancy(occupancy),.accepted(accepted),.full_drops(full_drops),.long_drops(long_drops));
    packet_codec #(.MAX_FRAME(MAX_FRAME)) codec(.valid(frame_valid),.frame_data(frame_data),.frame_length(frame_length),.frame_error(frame_error),
        .accept(accept),.kind(kind),.drop_reason(drop_reason),.reply_data(reply_data),.reply_length(reply_length));
    // The NIC uses only validation/kind; the CPU constructs the transmitted packet.
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused_decode=&{1'b0,reply_data,reply_length,drop_reason,occupancy,accepted,rdata[31:8]};
    /* verilator lint_on UNUSEDSIGNAL */
    reg [31:0] rejected;
    wire rx_busy=rx_state!=IDLE,tx_busy=tx_state!=IDLE;
    wire access=psel&&penable&&pready;
    assign pready=psel&&penable&&wait_count>=WAIT_CYCLES;
    wire valid_offset=paddr<=8'h2c && paddr[1:0]==0;
    wire config_busy=rx_owned||tx_busy;
    wire bad_control=pwdata[31:3]!=0 || pwdata[2:1]==3 || (run && !pwdata[0]) || (pwdata[1] && (tx_busy || !run || !rx_owned || rx_busy || tx_length<64 || tx_length>MAX_FRAME)) ||
        (pwdata[2] && (!rx_owned || rx_busy || tx_busy)) || ((!pwdata[0]) && (rx_busy||tx_busy||rx_owned));
    assign pslverr=!valid_offset || (pwrite && (paddr==8'h00 ? bad_control :
        (paddr==8'h08 || paddr==8'h0c) ? (config_busy || run || pwdata[1:0]!=0 || pwdata<32'h1000 || pwdata>32'h2000-32'(4*MAX_FRAME) ||
            (paddr==8'h08 ? (pwdata<tx_ptr+32'(4*MAX_FRAME) && tx_ptr<pwdata+32'(4*MAX_FRAME)) :
                            (pwdata<rx_ptr+32'(4*MAX_FRAME) && rx_ptr<pwdata+32'(4*MAX_FRAME)))) :
        paddr==8'h14 ? tx_busy : !(paddr==8'h04 || paddr==8'h28)));
    always @*begin
        prdata=0;
        case(paddr)
            8'h00:prdata={31'd0,run};8'h04:prdata={25'd0,rx_owned,tx_busy,rx_busy,status};
            8'h08:prdata=rx_ptr;8'h0c:prdata=tx_ptr;8'h10:prdata={16'd0,rx_length};8'h14:prdata=tx_length;
            8'h18:prdata=drop_count;8'h1c:prdata=rx_count;8'h20:prdata=tx_count;8'h24:prdata=last_error;8'h28:prdata={28'd0,mask};8'h2c:prdata={30'd0,rx_kind};
            default:prdata=0;
        endcase
    end
    assign irq=|(status&mask&(MUTATION==5 ? 4'b0111:4'b1111));
    assign frame_ready=run && frame_valid && (!accept || (!rx_owned && !rx_busy));
    assign awvalid=rx_state==ADDRESS;assign awaddr=rx_ptr+{14'd0,ri,2'b00}+(MUTATION==2 ? 32'd4:32'd0);
    assign awlen=0;assign awsize=2;assign awburst=1;assign awid=0;
    assign wvalid=rx_state==DATA;assign wdata={24'd0,rx_copy[8*ri+:8]};assign wstrb=15;assign wlast=1;
    assign bready=rx_state==RESPONSE;
    assign arvalid=tx_state==ADDRESS;assign araddr=tx_ptr+{14'd0,ti,2'b00};assign arlen=0;assign arsize=2;assign arburst=1;assign arid=0;
    assign rready=tx_state==DATA;
    assign tx_valid=rst_n && tx_state==SEND;assign tx_data=tx_copy[8*ti+:8];assign tx_last={16'd0,ti}==tx_length-1;
    wire rx_finish=rx_state==RESPONSE && bvalid && ri==rx_length-1;
    wire tx_finish=tx_state==SEND && tx_ready && tx_last;
    wire tx_failed=tx_state==DATA && rvalid && {16'd0,ti}==tx_length-1 && (tx_bad||rresp!=0||rid!=0||!rlast);
    wire [3:0] events={drop_count!=full_drops+long_drops+rejected,(rx_finish&&(rx_bad||bresp!=0||bid!=0))||tx_failed,
        tx_finish||(MUTATION==4 && tx_state==DATA && rvalid && {16'd0,ti}==tx_length-1 && !tx_bad && rresp==0 && rid==0 && rlast),
        (rx_finish&&!rx_bad&&bresp==0&&bid==0)||(MUTATION==1 && rx_state==DATA && wready && ri==rx_length-1)};
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            run<=0;rx_owned<=0;status<=0;mask<=0;rx_ptr<=32'h1000;tx_ptr<=32'h1400;tx_length<=0;
            rx_length<=0;rx_kind<=0;drop_count<=0;rx_count<=0;tx_count<=0;last_error<=0;rejected<=0;
            rx_state<=IDLE;tx_state<=IDLE;ri<=0;ti<=0;rx_bad<=0;tx_bad<=0;rx_copy<=0;tx_copy<=0;wait_count<=0;
        end else begin
            if(!psel || !penable)wait_count<=0;else if(!pready)wait_count<=wait_count+1;
            drop_count<=full_drops+long_drops+rejected;
            status<=(access && pwrite && !pslverr && paddr==4 ? status&~pwdata[3:0] : status)|events;
            if(access && pwrite && !pslverr)case(paddr)
                8'h00:begin
                    run<=pwdata[0];
                    if(pwdata[1])begin tx_state<=ADDRESS;ti<=0;tx_bad<=0;end
                    if(pwdata[2])rx_owned<=0;
                end
                8'h04:begin if(MUTATION==3 && pwdata[0])rx_owned<=0;end
                8'h08:rx_ptr<=pwdata;8'h0c:tx_ptr<=pwdata;8'h14:tx_length<=pwdata;8'h28:mask<=pwdata[3:0];
                default:begin end
            endcase
            // Event setting wins over simultaneous W1C, so completion cannot be lost.
            if(frame_valid && frame_ready)begin
                if(!accept)rejected<=rejected+1;
                else begin rx_owned<=1;rx_copy<=frame_data;rx_length<=frame_length;rx_kind<=kind;ri<=0;rx_bad<=0;rx_state<=ADDRESS;end
            end
            case(rx_state)
                ADDRESS:if(awready)rx_state<=DATA;
                DATA:if(wready)begin rx_state<=RESPONSE;end
                RESPONSE:if(bvalid)begin
                    rx_bad<=rx_bad||bresp!=0||bid!=0;
                    if(ri==rx_length-1)begin
                        rx_state<=IDLE;
                        if(rx_bad||bresp!=0||bid!=0)begin last_error<=1;end
                        else begin rx_count<=rx_count+1;end
                    end else begin ri<=ri+1;rx_state<=ADDRESS;end
                end
                default:begin end
            endcase
            case(tx_state)
                ADDRESS:if(arready)tx_state<=DATA;
                DATA:if(rvalid)begin
                    tx_copy[8*ti+:8]<=rdata[7:0];tx_bad<=tx_bad||rresp!=0||rid!=0||!rlast;
                    if({16'd0,ti}==tx_length-1)begin
                        ti<=0;
                        if(tx_bad||rresp!=0||rid!=0||!rlast)begin tx_state<=IDLE;last_error<=2;end
                        else begin tx_state<=SEND;end
                    end else begin ti<=ti+1;tx_state<=ADDRESS;end
                end
                SEND:if(tx_ready)begin
                    if(tx_last)begin tx_state<=IDLE;tx_count<=tx_count+1;end else ti<=ti+1;
                end
                default:begin end
            endcase
        end
    end
endmodule
