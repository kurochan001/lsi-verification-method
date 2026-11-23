// Educational mode-0 serial master. After a modifying frame the device presents
// a busy level during a separate selected interval, one sample per bit period.
module flash_ctrl #(parameter DIV=1, MUTATION=0)(
    input wire clk, rst_n, go,
    input wire [7:0] opcode, addr, wdata,
    input wire xip,
    output reg done, err, wel, wip,
    output wire [7:0] rdata,
    output reg spi_sclk, spi_csb,
    output wire spi_mosi,
    input wire spi_miso,
    input wire [7:0] flash_q
);
    localparam IDLE=0, SHIFT=1, GAP=2, POLL=3;
    localparam READ=8'h03, WREN=8'h06, PROGRAM=8'hA0, SECTOR=8'h32,
               ERASE=8'hD8, CLEAR=8'hC7;
    reg [1:0] state;
    reg [7:0] command, received, last_read;
    reg [31:0] tx;
    reg [5:0] remaining;
    reg [2:0] polls;
    integer ticks;
    wire write_cmd = opcode == PROGRAM || opcode == SECTOR || opcode == ERASE;
    wire legal = write_cmd || opcode == READ || opcode == WREN || opcode == CLEAR;
    wire [7:0] reversed = {wdata[0], wdata[1], wdata[2], wdata[3],
                           wdata[4], wdata[5], wdata[6], wdata[7]};
    assign spi_mosi = state == SHIFT && tx[31];
    assign rdata = state != IDLE ? 8'hff : xip ? flash_q : last_read;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; done <= 0; err <= 0; wel <= 0; wip <= 0;
            spi_sclk <= 0; spi_csb <= 1; command <= 0; received <= 0;
            last_read <= 0; tx <= 0; remaining <= 0; polls <= 0; ticks <= 0;
        end else begin
            done <= 0;
            err <= 0;
            case (state)
                IDLE: if (go && !xip) begin
                    if (!legal || (write_cmd && !wel && MUTATION != 1))
                        err <= 1;
                    else begin
                        state <= SHIFT;
                        command <= opcode;
                        tx <= {opcode, addr, (MUTATION == 3 && opcode == PROGRAM ? reversed : wdata), 8'd0};
                        case (opcode)
                            READ: begin tx <= {opcode, addr, 16'd0}; remaining <= 32; end
                            PROGRAM: remaining <= 24;
                            SECTOR: remaining <= 16;
                            default: remaining <= 8;
                        endcase
                        ticks <= 0; spi_csb <= 0; received <= 0;
                    end
                end
                SHIFT: if (ticks == DIV-1) begin
                    ticks <= 0;
                    spi_sclk <= !spi_sclk;
                    if (!spi_sclk) begin
                        received <= {received[6:0], spi_miso};
                        if (command == READ && remaining == 9)
                            wip <= spi_miso;
                    end else if (remaining == 1) begin
                        spi_csb <= 1;
                        wel <= command == WREN;
                        if (command == READ || command == WREN) begin
                            state <= IDLE;
                            if (command == READ) last_read <= received;
                            done <= command == WREN || !wip;
                            err <= command == READ && wip;
                        end else state <= GAP;
                    end else begin
                        remaining <= remaining - 1'b1;
                        tx <= {tx[30:0], 1'b0};
                    end
                end else ticks <= ticks + 1;
                GAP: begin
                    spi_csb <= 0;
                    polls <= 0;
                    state <= POLL;
                end
                POLL: if (ticks == 2*DIV-1) begin
                    ticks <= 0;
                    wip <= spi_miso || (MUTATION == 4 && wip);
                    if (!spi_miso || polls == (MUTATION == 2 ? 5 : 6)) begin
                        done <= !spi_miso;
                        err <= spi_miso;
                        spi_csb <= 1;
                        state <= IDLE;
                    end else polls <= polls + 1'b1;
                end else ticks <= ticks + 1;
            endcase
        end
    end
endmodule
