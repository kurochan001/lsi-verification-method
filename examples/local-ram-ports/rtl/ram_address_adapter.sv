// Byte-addressed aligned word transfers or native word-index transfers.
// Range checks use the full address before narrowing the RAM word index.
module ram_address_adapter #(
    parameter DATA_W=32,DEPTH=16,ADDR_W=16,BASE_ADDR=256,MUTATION=0
)(
    input wire word_mode,input wire [ADDR_W-1:0] address,
    input wire [DATA_W/8-1:0] byte_enable,
    output wire [$clog2(DEPTH)-1:0] word_index,
    output reg [DATA_W/8-1:0] ram_mask,output wire address_error
);
    localparam LANES=DATA_W/8,SHIFT=$clog2(LANES),AW=$clog2(DEPTH);
    wire [31:0] relative=word_mode ? 32'(address):32'(address)-32'(BASE_ADDR);
    wire aligned=word_mode || relative%LANES==0;
    wire in_range=word_mode ? 32'(address)<DEPTH : 32'(address)>=BASE_ADDR && relative<DEPTH*LANES;
    wire [AW-1:0] decoded=AW'(word_mode ? relative :
        MUTATION==12 ? 32'(address)>>SHIFT :
        MUTATION==1 ? relative :
        MUTATION==2 ? relative>>(2*SHIFT) :
        MUTATION==3 ? relative>>2 : relative>>SHIFT);
    assign word_index=(!word_mode && MUTATION==11) ? decoded^AW'(1):decoded;
    assign address_error=!(MUTATION==5 || in_range) || !(MUTATION==4 || aligned);
    always @* begin
        for (integer lane=0;lane<LANES;lane=lane+1)
            ram_mask[lane]=MUTATION==7 ? byte_enable[LANES-1-lane]:byte_enable[lane];
    end
endmodule
