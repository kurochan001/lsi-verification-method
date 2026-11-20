// Counts enabled events up to 15, tracks the parity of the data bit and raises an alarm.
// Eight flops, synchronous active-low reset. ALARM_AT is the only thing the specification change touches.
module event_meter #(parameter ALARM_AT = 12) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    input  wire       clear,
    input  wire       din,
    output wire       busy,
    output wire       full,
    output wire [3:0] level,
    output wire       odd,
    output wire       warn
);
    localparam [1:0] IDLE = 2'd0, RUN = 2'd1, HOLD = 2'd2;
    localparam [3:0] LIMIT = ALARM_AT[3:0];
    reg [1:0] state;
    reg [3:0] count;
    reg       parity;
    reg       alarm;

    wire       counting = en && !clear && state != HOLD;

    always @(posedge clk) begin
        if (!rst_n) begin
            state  <= IDLE;
            count  <= 4'd0;
            parity <= 1'b0;
            alarm  <= 1'b0;
        end else begin
            alarm <= count >= LIMIT;
            if (clear) begin
                state  <= IDLE;
                count  <= 4'd0;
                parity <= 1'b0;
            end else if (counting) begin
                count  <= count + 4'd1;
                parity <= parity ^ din;
                state  <= (count == 4'd14) ? HOLD : RUN;
            end
        end
    end

    assign busy  = state == RUN;
    assign full  = state == HOLD;
    assign level = count;
    assign odd   = parity;
    assign warn  = alarm;
endmodule
