// Receive directly from line symbols. A fixed CRC residue validates the entire
// payload + FCS; DATA packet size is derived from the observed EOP.
module usb_linecode_rx #(parameter PKT=0, MUTATION=0)(
    input wire clk, rst_n,
    input wire [1:0] line,
    output reg done, stuff_err, pid_err, crc_err, format_err,
    output reg [3:0] pid, length_bytes,
    output reg [63:0] data
);
    localparam IDLE=0, SYNC=1, BODY=2, ENDING=3;
    reg [1:0] state, previous;
    reg [2:0] sync_index, ones;
    reg [1:0] se0_count;
    reg [7:0] count;
    reg [7:0] pid_byte;
    reg [79:0] received;
    reg [15:0] remainder;
    wire decoded = line == previous;
    wire [15:0] polynomial = PKT == 0 ? 16'h0014 : 16'ha001;
    wire [7:0] data_bits = count - 24;
    integer k;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; previous <= 2'b01; done <= 0; pid <= 0; length_bytes <= 0; data <= 0;
            pid_err <= 0; stuff_err <= 0; crc_err <= 0; format_err <= 0;
        end else begin
            done <= 0; previous <= line;
            case (state)
                IDLE: if (line == 2'b10) begin
                    state <= SYNC; sync_index <= 1; ones <= 0; count <= 0; received <= 0;
                    pid_err <= 0; stuff_err <= 0; crc_err <= 0; format_err <= 0;
                    remainder <= PKT == 0 ? 16'h001f : 16'hffff;
                end
                SYNC: begin
                    if (line == 2'b00 || line == 2'b11 || decoded != (sync_index == 7)) format_err <= 1;
                    if (sync_index == 7) begin state <= BODY; ones <= 1; end
                    sync_index <= sync_index + 1'b1;
                end
                BODY: begin
                    if (line == 2'b00) begin
                        state <= ENDING; se0_count <= 1;
                        if (ones == 6) stuff_err <= 1;
                    end else if (line == 2'b11) format_err <= 1;
                    else if (ones == 6) begin
                        if (decoded) stuff_err <= 1;
                        ones <= 0;
                    end else begin
                        ones <= decoded ? ones + 1'b1 : 0;
                        if (count < 8) pid_byte[count[2:0]] <= decoded;
                        else begin
                            remainder <= (remainder >> 1) ^ ((remainder[0] ^ decoded) ? polynomial : 16'h0);
                            if (count < 88) received[count-8] <= decoded;
                        end
                        if (count < 88) count <= count + 1'b1;
                        else format_err <= 1;
                    end
                end
                ENDING: begin
                    if (line == 2'b00) begin
                        if (se0_count < 3) se0_count <= se0_count + 1'b1;
                    end else begin
                        done <= 1; state <= IDLE;
                        if (line != 2'b01 || se0_count != 2) format_err <= 1;
                        if (PKT == 0 ? count != 24 : count < 24 || data_bits[2:0] != 0)
                            format_err <= 1;
                        pid <= pid_byte[3:0];
                        pid_err <= (pid_byte[7:4] != ~pid_byte[3:0]) ^ (MUTATION == 3);
                        crc_err <= remainder != (PKT == 0 ? 16'h0006 : 16'hb001);
                        length_bytes <= PKT == 0 ? 2 : data_bits[6:3];
                        for (k=0;k<64;k=k+1)
                            data[k] <= received[k] && (PKT == 0 ? k < 11 : k < data_bits);
                    end
                end
            endcase
        end
    end
endmodule
