module unaligned_memory #(
    parameter integer DATA_W=32, DEPTH=16, BIG_ENDIAN=0, MUTATION=0,
    parameter integer AW=$clog2(DEPTH)
)(
    input wire clk, rst_n,
    input wire req_valid, req_write,
    output wire req_ready,
    input wire [15:0] req_address,
    input wire [3:0] req_size,
    input wire [DATA_W-1:0] req_data,
    input wire fault_second,
    output reg rsp_valid,
    input wire rsp_ready,
    output reg [DATA_W-1:0] rsp_data,
    output reg rsp_error,
    output wire native_enable, native_write,
    output wire [AW-1:0] native_address
);
    localparam integer BYTES=DATA_W/8;
    localparam [1:0] IDLE=0, ISSUE=1, WAIT_DATA=2, RESPONSE=3;
    reg [1:0] state;
    reg writing, fail_second;
    reg [15:0] base;
    reg [3:0] size;
    reg [DATA_W-1:0] payload, assembled;
    integer progressed, chunk, absolute_byte, lane, value_byte;
    reg [DATA_W-1:0] native_data, read_assembled;
    reg [BYTES-1:0] native_strb;
    wire [DATA_W-1:0] native_read;
    wire second_error=(progressed!=0 && fail_second);
    wire second_dropped=(progressed!=0 && MUTATION==4);
    assign native_enable=rst_n && state==ISSUE && !second_error && !second_dropped;
    assign native_write=writing;
    assign native_address=AW'((int'(base)+progressed)/BYTES);
    assign req_ready=rst_n && state==IDLE;
    byte_word_ram #(.DATA_W(DATA_W),.DEPTH(DEPTH)) ram(
        .clk(clk),.enable(native_enable),.write(native_write),.address(native_address),
        .write_data(native_data),.byte_enable(native_strb),.read_data(native_read));
    always @* begin
        chunk=BYTES-((int'(base)+progressed)%BYTES);
        if(chunk>int'(size)-progressed)chunk=int'(size)-progressed;
        native_data='0;native_strb='0;read_assembled=assembled;
        absolute_byte=0;lane=0;value_byte=0;
        for(integer n=0;n<BYTES;n=n+1) begin
            if(n<chunk) begin
                absolute_byte=progressed+n;
                lane=(int'(base)+absolute_byte)%BYTES;
                if(MUTATION==1)lane=n;
                value_byte=(BIG_ENDIAN!=0 && MUTATION!=2) ? int'(size)-1-absolute_byte : absolute_byte;
                native_data[lane*8+:8]=payload[value_byte*8+:8];
                native_strb[lane]=1'b1;
                read_assembled[value_byte*8+:8]=native_read[lane*8+:8];
            end
        end
        if(MUTATION==3)native_strb='1;
    end
    always @(posedge clk) begin
        if(!rst_n) begin
            state<=IDLE;rsp_valid<=0;rsp_data<='0;rsp_error<=0;
            writing<=0;fail_second<=0;base<=0;size<=0;
            payload<='0;assembled<='0;progressed<=0;
        end else case(state)
            IDLE: if(req_valid && req_ready) begin
                writing<=req_write;fail_second<=fault_second;base<=req_address;
                size<=req_size;payload<=req_data;progressed<=0;assembled<='0;
                rsp_data<='0;rsp_error<=0;
                if(req_size==0 || int'(req_size)>BYTES || int'(req_address)+int'(req_size)>DEPTH*BYTES) begin
                    rsp_error<=1;rsp_valid<=1;state<=RESPONSE;
                end else state<=ISSUE;
            end
            ISSUE: begin
                if(second_error)begin rsp_error<=1;rsp_data<='0;rsp_valid<=1;state<=RESPONSE;end
                else if(second_dropped)begin rsp_valid<=1;rsp_data<=assembled;state<=RESPONSE;end
                else state<=WAIT_DATA;
            end
            WAIT_DATA: begin
                if(!writing)assembled<=read_assembled;
                if(progressed+chunk==int'(size))begin
                    rsp_data<=writing ? '0 : read_assembled;rsp_valid<=1;state<=RESPONSE;
                end else begin progressed<=progressed+chunk;state<=ISSUE;end
            end
            RESPONSE: if(rsp_valid && rsp_ready)begin rsp_valid<=0;state<=IDLE;end
            default:state<=IDLE;
        endcase
    end
endmodule
