// Word alignment on the comma (0011111 or 1100000), one received bit per valid cycle.
// A comma in the first seven bits of the last ten received bits marks a word boundary. With
// align_en low, a comma off the current boundary is ignored. The registered outputs show, one
// cycle after the last bit of a word, the word and a one-cycle word_valid; realigned marks a
// word whose boundary moved an alignment that already existed.
// MUTATION: 8 only 0011111 is detected, 9 align_en is ignored.
module comma_align #(parameter MUTATION = 0) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       align_en,
    input  wire       bit_valid,
    input  wire       bit_in,
    output reg        word_valid,
    output reg  [9:0] word,
    output reg        aligned,
    output reg        realigned
);
    reg [8:0] window;   // the nine bits before the one arriving now
    reg [3:0] filled, phase;
    wire [9:0] next_window = {window, bit_in};
    wire comma = filled >= 4'd9 && (next_window[9:3] == 7'b0011111 ||
                                    (next_window[9:3] == 7'b1100000 && MUTATION != 8));
    wire boundary = aligned && phase == 4'd9;
    wire move = comma && (align_en || MUTATION == 9) && !boundary;
    always @(posedge clk) begin
        if (!rst_n) begin
            window <= 9'd0;
            filled <= 4'd0;
            phase <= 4'd0;
            word <= 10'd0;
            word_valid <= 1'b0;
            aligned <= 1'b0;
            realigned <= 1'b0;
        end else begin
            word_valid <= 1'b0;
            realigned <= 1'b0;
            if (bit_valid) begin
                window <= next_window[8:0];
                if (filled < 4'd10) filled <= filled + 4'd1;
                if (move || boundary) begin
                    phase <= 4'd0;
                    word <= next_window;
                    word_valid <= 1'b1;
                    aligned <= 1'b1;
                    realigned <= move && aligned;
                end else if (aligned) begin
                    phase <= phase + 4'd1;
                end
            end
        end
    end
endmodule
