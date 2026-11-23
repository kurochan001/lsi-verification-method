// Simulation peer. Decode only transfers observed on the serial pins. A high
// CS ends one frame. A selected interval with no SCLK edges is the busy poll.
module flash_model #(parameter DIV=1)(
    input wire clk, rst_n, csb, sclk, mosi, xip_en,
    input wire [7:0] xip_addr,
    output wire [7:0] q,
    output wire miso, wel, wip
);
    reg [7:0] mem [0:15];
    reg [7:0] frame;
    reg [5:0] bits;
    reg [7:0] command, address;
    reg prev_csb, prev_sclk, enabled, fault, sampled_so;
    integer busy_ticks, k;
    wire [7:0] serial_data = address < 16 ? mem[address[3:0]] : 8'hff;
    wire status = busy_ticks != 0 || fault;
    assign q = xip_en && xip_addr < 16 ? mem[xip_addr[3:0]] : 8'hff;
    assign wel = enabled;
    assign wip = busy_ticks != 0;
    wire next_so = csb ? 1'b0 :
                  command == 8'h03 && bits >= 24 ? serial_data[7-bits[2:0]] :
                  command == 8'h03 && bits >= 16 ? (bits == 23 && status) : status;

    assign miso = sclk ? sampled_so : next_so;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (k=0; k<16; k=k+1) mem[k] <= 8'ha0 ^ 8'(k);
            frame <= 0; bits <= 0; command <= 0; address <= 0;
            sampled_so <= 0; prev_csb <= 1; prev_sclk <= 0; enabled <= 0; fault <= 0; busy_ticks <= 0;
        end else begin
            if (!sclk) sampled_so <= next_so;
            prev_csb <= csb; prev_sclk <= sclk;
            if (busy_ticks != 0) busy_ticks <= busy_ticks - 1;
            if (!csb && sclk && !prev_sclk) begin
                frame <= {frame[6:0], mosi};
                bits <= bits + 1'b1;
                if (bits == 7) command <= {frame[6:0], mosi};
                if (bits == 15) address <= {frame[6:0], mosi};
            end
            if (csb && !prev_csb) begin
                if (bits != 0) enabled <= command == 8'h06 && bits == 8;
                case (command)
                    8'ha0: if (bits == 24 && enabled) begin
                        if (address >= 16 || (frame[7:0] & ~serial_data) != 0)
                            fault <= 1;
                        else if (!fault) begin
                            mem[address[3:0]] <= frame[7:0];
                            busy_ticks <= 4*2*DIV;
                        end
                    end
                    8'h32: if (bits == 16 && enabled && !fault) begin
                        if (address >= 16) fault <= 1;
                        else begin
                            for (k=0; k<16; k=k+1)
                                if (k[3:2] == address[3:2]) mem[k] <= 8'hff;
                            busy_ticks <= 6*2*DIV;
                        end
                    end
                    8'hd8: if (bits == 8 && enabled && !fault) begin
                        for (k=0; k<16; k=k+1) mem[k] <= 8'hff;
                        busy_ticks <= 6*2*DIV;
                    end
                    8'hc7: if (bits == 8) begin
                        busy_ticks <= fault ? 4*2*DIV : 0;
                        fault <= 0;
                    end
                    default: ;
                endcase
                bits <= 0; frame <= 0; command <= 0; address <= 0;
            end
        end
    end
endmodule
