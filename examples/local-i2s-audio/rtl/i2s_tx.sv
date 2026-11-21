// I2S master transmitter. sck is the system clock divided by two. ws and sd change together
// with the falling edge of sck, and ws changes one bit period before the first (most
// significant) bit of the word it announces: ws low announces the left word.
module i2s_tx #(parameter WORD = 16, SLOT = 16, MUTATION = 0) (
    input             clk,
    input             rst_n,
    input             in_valid,
    output            in_ready,
    input  [WORD-1:0] in_left,
    input  [WORD-1:0] in_right,
    output reg        sck,
    output reg        ws,
    output reg        sd,
    output reg        underrun
);
    localparam FRAME = 2 * SLOT;
    localparam PW = $clog2(FRAME);
    localparam [31:0] LAST32 = FRAME - 1;
    localparam [31:0] SLOT32 = SLOT;
    localparam [PW-1:0] LAST = LAST32[PW-1:0];
    localparam [PW-1:0] HALF = SLOT32[PW-1:0];

    reg [WORD-1:0]  hold_left, hold_right;
    reg             hold_valid;
    reg [PW-1:0]    pos;                    // position in the frame of the bit now on sd
    reg [FRAME-1:0] shift;

    assign in_ready = !hold_valid;

    wire [PW-1:0] next  = pos == LAST ? {PW{1'b0}} : pos + 1'b1;
    wire [PW-1:0] after = next == LAST ? {PW{1'b0}} : next + 1'b1;
    wire [PW-1:0] announced = MUTATION == 1 ? next : after;      // 1: ws does not lead the word

    // 2: least significant bit first.
    wire [WORD-1:0] rev_left, rev_right;
    genvar g;
    generate
        for (g = 0; g < WORD; g = g + 1) begin : reverse
            assign rev_left[g]  = hold_left[WORD-1-g];
            assign rev_right[g] = hold_right[WORD-1-g];
        end
    endgenerate
    wire [WORD-1:0] word_left  = MUTATION == 2 ? rev_left : hold_left;
    wire [WORD-1:0] word_right = MUTATION == 2 ? rev_right : hold_right;

    wire [SLOT-1:0] slot_left, slot_right;
    generate
        if (SLOT == WORD) begin : exact
            assign slot_left  = word_left;
            assign slot_right = word_right;
        end else begin : padded
            assign slot_left  = {word_left, {(SLOT-WORD){1'b0}}};
            assign slot_right = {word_right, {(SLOT-WORD){1'b0}}};
        end
    endgenerate
    // 3: the two channels change places.
    wire [FRAME-1:0] pair = MUTATION == 3 ? {slot_right, slot_left} : {slot_left, slot_right};
    wire [FRAME-1:0] loaded = hold_valid ? pair : {FRAME{1'b0}};

    always @(posedge clk) begin
        if (!rst_n) begin
            sck <= 1'b0;
            ws <= 1'b1;
            sd <= 1'b0;
            underrun <= 1'b0;
            hold_valid <= 1'b0;
            hold_left <= {WORD{1'b0}};
            hold_right <= {WORD{1'b0}};
            pos <= LAST - 1'b1;
            shift <= {FRAME{1'b0}};
        end else begin
            underrun <= 1'b0;
            sck <= !sck;
            if (in_valid && in_ready) begin
                hold_valid <= 1'b1;
                hold_left <= in_left;
                hold_right <= in_right;
            end
            if (sck) begin                              // this edge is the falling edge of sck
                pos <= next;
                ws <= announced >= HALF;
                if (next == {PW{1'b0}}) begin           // a new frame starts with what is waiting
                    sd <= loaded[FRAME-1];
                    shift <= {loaded[FRAME-2:0], 1'b0};
                    if (hold_valid) hold_valid <= 1'b0;
                    else underrun <= MUTATION != 4;     // 4: an empty frame is not reported
                end else begin
                    sd <= shift[FRAME-1];
                    shift <= {shift[FRAME-2:0], 1'b0};
                end
            end
        end
    end
endmodule
