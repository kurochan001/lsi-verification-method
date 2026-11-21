// Byte-stream checksum: CRC-16 (polynomial 0x1021, most significant bit first,
// no reflection, no final XOR) and a saturating byte count, reported with `last`.
module packet_sum #(
    parameter int INIT = 65535,
    parameter int MUTATION = 0
) (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        valid,
    input  logic [7:0]  data,
    input  logic        last,
    output logic        done,
    output logic [15:0] crc,
    output logic [7:0]  length
);
    localparam logic [15:0] START = 16'(INIT);
    localparam logic [15:0] POLY = MUTATION == 1 ? 16'h1020 : 16'h1021;

    logic [15:0] crc_q;
    logic [7:0]  length_q;
    logic [15:0] crc_next;
    logic [7:0]  length_next;
    logic        count_enable;

    function automatic logic [15:0] step(input logic [15:0] value, input logic [7:0] in);
        logic [15:0] acc;
        acc = value;
        for (int i = 7; i >= 0; i--)
            acc = (acc[15] ^ in[i]) ? {acc[14:0], 1'b0} ^ POLY : {acc[14:0], 1'b0};
        return acc;
    endfunction

    assign crc_next = step(crc_q, data);
    assign length_next = length_q == 8'hff ? 8'hff : length_q + 8'd1;
    assign count_enable = valid || MUTATION == 3;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            // Mutation 4 keeps the running CRC when the reset arrives inside a packet.
            if (MUTATION != 4 || length_q == 8'd0) crc_q <= START;
            length_q <= 8'd0;
            done <= 1'b0;
            crc <= 16'd0;
            length <= 8'd0;
        end else begin
            done <= valid && (last || (MUTATION == 5 && length_q == 8'd3));
            if (count_enable && !(valid && last)) length_q <= length_next;
            if (valid) begin
                crc_q <= crc_next;
                if (last) begin
                    crc <= crc_next;
                    length <= length_next;
                    length_q <= 8'd0;
                    if (MUTATION != 2) crc_q <= START;
                end
            end
        end
    end
endmodule
