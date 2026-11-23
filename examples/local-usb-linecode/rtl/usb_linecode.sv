// Full-speed logical symbols: J=01, K=10, SE0=00, SE1=11.
// One posedge per bit cell. Payload bit 0 is transmitted first.
module usb_linecode #(parameter PKT=0, MUTATION=0)(
    input wire clk, rst_n, start,
    input wire [3:0] pid, nbytes,
    input wire [63:0] payload,
    output reg [1:0] line,
    output reg busy
);
    localparam SYNC=0, BODY=1, STUFF_END=2, EOP=3;
    reg [1:0] state;
    reg [6:0] position, payload_width, end_bit;
    reg [2:0] ones;
    reg [1:0] eop_count;
    reg [7:0] pid_reg;
    reg [63:0] data_reg;
    reg [15:0] crc;
    wire in_payload = position >= 8 && position < 8 + payload_width;
    wire stuff = ones == (MUTATION == 1 ? 7 : 6);
    wire [3:0] crc_index = position[3:0] - 4'd8 - payload_width[3:0];
    wire raw_bit = position < 8 ? pid_reg[position[2:0]] :
                   in_payload ? data_reg[position-8] : !crc[crc_index];
    wire tx_bit = state == SYNC ? position == 7 : ((state == STUFF_END || stuff) ? 1'b0 : raw_bit);
    wire change_level = MUTATION == 4 ? tx_bit : !tx_bit;
    wire [15:0] polynomial = PKT == 0 ? 16'h0014 : 16'ha001;
    wire [6:0] data_width = PKT == 0 ? 7'd11 : {nbytes,3'b000};
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin busy <= 0; line <= 2'b01; end
        else if (!busy) begin
            if (start && (PKT == 0 || nbytes <= 8)) begin
                busy <= 1; state <= SYNC; position <= 0; ones <= 0;
                pid_reg <= {~pid,pid}; data_reg <= payload;
                payload_width <= data_width;
                end_bit <= 8 + data_width + (PKT == 0 ? 5 : 16) - 1;
                crc <= MUTATION == 2 ? 0 : (PKT == 0 ? 16'h001f : 16'hffff);
                eop_count <= 0;
            end
        end else if (state == EOP) begin
            if (eop_count == 2) begin line <= 2'b01; busy <= 0; end
            else begin line <= 2'b00; eop_count <= eop_count + 1'b1; end
        end else begin
            if (change_level) line <= ~line;
            case (state)
                SYNC: begin
                    position <= position + 1'b1;
                    if (position == 7) begin state <= BODY; position <= 0; ones <= 1; end
                end
                BODY: begin
                    ones <= tx_bit ? ones + 1'b1 : 0;
                    if (!stuff) begin
                        position <= position + 1'b1;
                        if (in_payload)
                            crc <= (crc >> 1) ^ ((crc[0] ^ raw_bit) ? polynomial : 16'h0);
                        if (position == end_bit)
                            state <= (raw_bit && ones == (MUTATION == 1 ? 6 : 5)) ? STUFF_END : EOP;
                    end
                end
                STUFF_END: state <= EOP;
                default: state <= EOP;
            endcase
        end
    end
endmodule
