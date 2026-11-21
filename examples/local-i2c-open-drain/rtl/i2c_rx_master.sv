// Reading side of an I2C controller, reduced to the data phase of one byte.
// SCL is driven low for DIV clocks and released for DIV clocks per bit. SDA is sampled
// SAMPLE clocks after SCL was released, most significant bit first. After the eighth bit
// SCL is held low for one more phase (where the target releases SDA) and then released.
// This is a teaching model of the sampling point, not an I2C IP: no START, address, ACK,
// clock stretching or arbitration.
module i2c_rx_master #(parameter DIV = 125, SAMPLE = 62, MUTATION = 0) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start,
    input  wire       sda_in,
    output reg        scl,
    output reg        busy,
    output reg        done,
    output reg        smp,
    output reg  [7:0] data
);
    localparam integer CW = $clog2(DIV + 1);
    localparam integer SMP_I = (MUTATION == 1) ? SAMPLE - 1 : SAMPLE;     // 1: samples one clock early
    localparam integer HIGH_I = (MUTATION == 3) ? DIV - 1 : DIV;          // 3: high phase one clock short
    localparam [CW-1:0] LAST = DIV[CW-1:0];
    localparam [CW-1:0] SMP = SMP_I[CW-1:0];
    localparam [CW-1:0] HIGH_LAST = HIGH_I[CW-1:0];
    localparam [3:0] BITS = (MUTATION == 5) ? 4'd7 : 4'd8;               // 5: stops after seven bits

    reg [CW-1:0] cnt;
    reg [3:0]    bits;
    reg          tail;

    always @(posedge clk) begin
        smp  <= 1'b0;
        done <= 1'b0;
        if (!rst_n) begin
            scl <= 1'b1; busy <= 1'b0; cnt <= {CW{1'b0}}; bits <= 4'd0; tail <= 1'b0; data <= 8'd0;
        end else if (!busy) begin
            if (start) begin
                scl <= 1'b0; busy <= 1'b1; cnt <= {{(CW-1){1'b0}}, 1'b1}; bits <= 4'd0; tail <= 1'b0;
            end
        end else if (!scl) begin
            // 4: samples in the low phase instead of the high phase
            if (MUTATION == 4 && !tail && cnt == SMP) begin
                smp <= 1'b1; data <= {data[6:0], sda_in}; bits <= bits + 4'd1;
            end
            if (cnt == LAST) begin
                cnt <= {{(CW-1){1'b0}}, 1'b1};
                if (tail) begin
                    scl <= (MUTATION == 6) ? 1'b0 : 1'b1;                    // 6: SCL not released at the end
                    busy <= 1'b0;
                    done <= 1'b1;
                end else begin
                    scl <= 1'b1;
                end
            end else begin
                cnt <= cnt + {{(CW-1){1'b0}}, 1'b1};
            end
        end else begin
            if (MUTATION != 4 && cnt == SMP) begin
                smp <= 1'b1;
                data <= (MUTATION == 2) ? {sda_in, data[7:1]} : {data[6:0], sda_in};   // 2: LSB first
                bits <= bits + 4'd1;
            end
            if (cnt == HIGH_LAST) begin
                cnt <= {{(CW-1){1'b0}}, 1'b1};
                scl <= 1'b0;
                if (bits == BITS) tail <= 1'b1;
            end else begin
                cnt <= cnt + {{(CW-1){1'b0}}, 1'b1};
            end
        end
    end
endmodule
