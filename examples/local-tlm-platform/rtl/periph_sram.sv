// 64-word memory, cleared by reset, read combinationally.
module periph_sram #(parameter MUTATION = 0) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        we,
    input  wire [5:0]  index,
    input  wire [31:0] wdata,
    output wire [31:0] rdata
);
    reg [31:0] mem [0:63];
    // Mutation 3: the top index bit is dropped, so words 32..63 alias 0..31.
    wire [5:0] slot = MUTATION == 3 ? {1'b0, index[4:0]} : index;
    // Mutation 7: writes to words 48..63 are lost.
    wire keep = we && !(MUTATION == 7 && slot[5:4] == 2'b11);
    assign rdata = mem[slot];
    integer i;

    always @(posedge clk) begin
        if (!rst_n) begin
            for (i = 0; i < 64; i = i + 1) mem[i] <= 32'd0;
        end else if (keep) begin
            mem[slot] <= wdata;
        end
    end
endmodule
