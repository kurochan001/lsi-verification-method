// I2S slave receiver, clocked by the incoming sck. It samples ws and sd on the rising edge.
// A change of ws seen on one edge means that the next edge carries the first bit of the new
// word; the edge that sees the change still carries the last bit of the old slot.
// Bits beyond WORD are ignored and missing bits read as zero. A slot whose length is not
// SLOT is counted in errors.
module i2s_rx #(parameter WORD = 16, SLOT = 16, MUTATION = 0) (
    input                 sck,
    input                 rst_n,
    input                 ws,
    input                 sd,
    output reg [WORD-1:0] left,
    output reg [WORD-1:0] right,
    output reg [7:0]      frames,
    output reg [7:0]      errors
);
    localparam CW = $clog2(SLOT + 2);
    localparam [31:0] SLOT32 = SLOT;
    localparam [CW-1:0] FULL = SLOT32[CW-1:0] - 1'b1;       // samples before the last bit of a good slot
    localparam [CW-1:0] TOP = SLOT32[CW-1:0] + 1'b1;        // the length counter stops here
    localparam [WORD-1:0] MSB = {1'b1, {(WORD-1){1'b0}}};

    reg            seen, armed, ws_d, channel, have_left;
    reg [CW-1:0]   count;
    reg [WORD-1:0] shift, mask, left_hold;

    wire change = seen && ws != ws_d;
    wire [WORD-1:0] placed = sd ? shift | mask : shift;
    // 6: bits after the word keep shifting in instead of being ignored.
    wire [WORD-1:0] taken = mask != {WORD{1'b0}} ? placed :
                            MUTATION == 6 ? {shift[WORD-2:0], sd} : shift;
    // 5: the edge that sees the change is taken as the first bit of the new word.
    wire [WORD-1:0] word = MUTATION == 5 ? shift : taken;
    // 7: only a slot that is too long is counted.
    wire bad_length = MUTATION == 7 ? count > FULL : count != FULL;

    always @(posedge sck or negedge rst_n) begin
        if (!rst_n) begin
            seen <= 1'b0;
            armed <= 1'b0;
            ws_d <= 1'b0;
            channel <= 1'b0;
            have_left <= 1'b0;
            count <= {CW{1'b0}};
            shift <= {WORD{1'b0}};
            mask <= MSB;
            left_hold <= {WORD{1'b0}};
            left <= {WORD{1'b0}};
            right <= {WORD{1'b0}};
            frames <= 8'd0;
            errors <= 8'd0;
        end else begin
            seen <= 1'b1;
            ws_d <= ws;
            if (change) begin
                if (armed) begin
                    if (bad_length) errors <= errors + 8'd1;
                    if (!channel) begin
                        left_hold <= word;
                        have_left <= 1'b1;
                    end else if (have_left) begin
                        left <= left_hold;
                        right <= word;
                        frames <= frames + 8'd1;
                        have_left <= 1'b0;
                    end
                end
                armed <= 1'b1;
                channel <= ws;
                count <= {CW{1'b0}};
                shift <= MUTATION == 5 && sd ? MSB : {WORD{1'b0}};
                mask <= MUTATION == 5 ? {1'b0, MSB[WORD-1:1]} : MSB;
            end else if (armed) begin
                shift <= taken;
                mask <= {1'b0, mask[WORD-1:1]};
                if (count != TOP) count <= count + 1'b1;
            end
        end
    end
endmodule
