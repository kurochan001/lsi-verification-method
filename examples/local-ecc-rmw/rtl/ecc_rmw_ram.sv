module ecc_rmw_ram #(
    parameter integer DATA_W = 32,
    parameter integer DEPTH = 8,
    parameter integer MUTATION = 0,
    parameter integer AW = $clog2(DEPTH),
    parameter integer PARITY = (DATA_W == 64 ? 7 : 6),
    parameter integer CODE_W = DATA_W + PARITY + 1
)(
    input wire clk, rst_n,
    input wire req_valid, req_write,
    output wire req_ready,
    input wire [AW-1:0] req_addr,
    input wire [DATA_W-1:0] req_data,
    input wire [DATA_W/8-1:0] req_strb,
    output reg rsp_valid,
    input wire rsp_ready,
    output reg [DATA_W-1:0] rsp_data,
    output reg rsp_corrected, rsp_uncorrectable, rsp_error,
    input wire scrub_enable,
    output reg scrub_done, scrub_corrected, scrub_uncorrectable,
    input wire inject_valid,
    output wire inject_ready,
    input wire [AW-1:0] inject_addr,
    input wire [CODE_W-1:0] inject_mask,
    output wire busy
);
    localparam integer BYTES = DATA_W/8;
    localparam [2:0] IDLE=0, READ=1, DECODE=2, WRITE=3, RESPONSE=4;
    reg [2:0] state;
    reg [CODE_W-1:0] memory [0:DEPTH-1];
    reg [CODE_W-1:0] read_word, write_word;
    reg [AW-1:0] address, scrub_address;
    reg [DATA_W-1:0] data;
    reg [BYTES-1:0] strb;
    reg writing, scrubbing;

    function automatic [CODE_W-1:0] encode(input [DATA_W-1:0] value);
        reg [CODE_W-1:0] code;
        integer pos, bit_index, parity_index;
        begin
            code='0; bit_index=0;
            for (pos=1; pos<CODE_W; pos=pos+1)
                if ((pos & (pos-1)) != 0) begin
                    code[pos-1]=value[bit_index]; bit_index=bit_index+1;
                end
            for (parity_index=0; parity_index<PARITY; parity_index=parity_index+1)
                for (pos=1; pos<CODE_W; pos=pos+1)
                    if ((pos & (1<<parity_index)) != 0 && pos != (1<<parity_index))
                        code[(1<<parity_index)-1]=code[(1<<parity_index)-1]^code[pos-1];
            code[CODE_W-1]=^code[CODE_W-2:0];
            encode=code;
        end
    endfunction

    reg [CODE_W-1:0] corrected_word, stale_word;
    reg [DATA_W-1:0] decoded, merged;
    reg correctable, uncorrectable;
    integer syndrome, pos, index, lane;
    always @* begin
        syndrome=0;
        for (pos=1; pos<CODE_W; pos=pos+1)
            if (read_word[pos-1]) syndrome=syndrome^pos;
        correctable=^read_word;
        uncorrectable=(syndrome != 0) && !correctable;
        corrected_word=read_word;
        if (correctable) begin
            if (syndrome == 0) corrected_word[CODE_W-1]=~read_word[CODE_W-1];
            else if (syndrome < CODE_W) corrected_word[syndrome-1]=~read_word[syndrome-1];
        end
        decoded='0; index=0;
        for (pos=1; pos<CODE_W; pos=pos+1)
            if ((pos & (pos-1)) != 0) begin
                decoded[index]=corrected_word[pos-1]; index=index+1;
            end
        merged=decoded;
        for (lane=0; lane<BYTES; lane=lane+1)
            if (strb[lane] || MUTATION==1) merged[8*lane+:8]=data[8*lane+:8];
        stale_word=read_word; index=0;
        for (pos=1; pos<CODE_W; pos=pos+1)
            if ((pos & (pos-1)) != 0) begin stale_word[pos-1]=merged[index]; index=index+1; end
    end

    assign busy=(state != IDLE);
    assign inject_ready=rst_n && state==IDLE && !rsp_valid;
    assign req_ready=inject_ready && !inject_valid;
    always @(posedge clk) begin
        if (!rst_n) begin
            state<=IDLE; rsp_valid<=0; rsp_data<='0;
            rsp_corrected<=0; rsp_uncorrectable<=0; rsp_error<=0;
            scrub_done<=0; scrub_corrected<=0; scrub_uncorrectable<=0;
            address<='0; scrub_address<='0; data<='0; strb<='0;
            read_word<='0; write_word<='0; writing<=0; scrubbing<=0;
        end else begin
            scrub_done<=0;
            case (state)
                IDLE: begin
                    if (inject_valid && inject_ready)
                        memory[inject_addr]<=memory[inject_addr]^inject_mask;
                    else if (req_valid && req_ready) begin
                        address<=req_addr; data<=req_data; strb<=req_strb;
                        writing<=req_write; scrubbing<=0;
                        rsp_data<='0; rsp_corrected<=0; rsp_uncorrectable<=0; rsp_error<=0;
                        if (req_write && req_strb=='0) begin rsp_valid<=1; state<=RESPONSE; end
                        else if (req_write && &req_strb) begin
                            write_word<=encode(req_data); state<=WRITE;
                        end else state<=READ;
                    end else if (scrub_enable) begin
                        address<=scrub_address; writing<=0; scrubbing<=1; state<=READ;
                    end
                end
                READ: begin read_word<=memory[address]; state<=DECODE; end
                DECODE: begin
                    if (scrubbing) begin
                        scrub_corrected<=correctable; scrub_uncorrectable<=uncorrectable;
                    end else begin
                        rsp_data<=writing || uncorrectable ? '0 : decoded;
                        rsp_corrected<=MUTATION==3 ? 1'b0 : correctable;
                        rsp_uncorrectable<=uncorrectable; rsp_error<=uncorrectable;
                    end
                    if (!uncorrectable && (writing || correctable)) begin
                        write_word<=writing ? encode(merged) : corrected_word;
                        if (MUTATION==2 && writing) begin
                            // Deliberate bug: update payload bits but keep stale check bits.
                            write_word<=stale_word;
                        end
                        if (MUTATION==4 && writing && scrub_enable)
                            write_word<=corrected_word;
                        state<=WRITE;
                    end else if (scrubbing) begin
                        scrub_done<=1; scrub_address<=scrub_address==AW'(DEPTH-1) ? '0 : scrub_address+1'b1;
                        state<=IDLE;
                    end else begin rsp_valid<=1; state<=RESPONSE; end
                end
                WRITE: begin
                    memory[address]<=write_word;
                    if (scrubbing) begin
                        scrub_done<=1; scrub_address<=scrub_address==AW'(DEPTH-1) ? '0 : scrub_address+1'b1;
                        state<=IDLE;
                    end else begin rsp_valid<=1; state<=RESPONSE; end
                end
                RESPONSE: if (rsp_valid && rsp_ready) begin rsp_valid<=0; state<=IDLE; end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
