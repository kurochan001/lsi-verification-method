module adc_capture #(
    parameter integer BITS = 8,
    parameter integer LSB_UV = 1000,
    parameter integer ACQUIRE = 2,
    parameter integer CONVERT = 4,
    parameter integer MUTATION = 0
)(
    input wire clk, rst_n,
    input wire start,
    input wire signed [31:0] vin_uv,
    output wire start_ready,
    output wire busy,
    output reg overrun,
    output reg result_valid,
    input wire result_ready,
    output reg [BITS-1:0] result_code
);
    localparam integer TIMER_W = $clog2((ACQUIRE > CONVERT ? ACQUIRE : CONVERT) + 1);
    localparam integer MAX_CODE = (1 << BITS) - 1;
    localparam [1:0] IDLE = 0, ACQUIRING = 1, CONVERTING = 2;

    reg [1:0] state;
    reg [TIMER_W-1:0] remaining;
    reg [BITS-1:0] sampled_code;

    function automatic [BITS-1:0] quantize(input signed [31:0] voltage_uv);
        if (voltage_uv <= 0)
            quantize = '0;
        else if (voltage_uv >= MAX_CODE * LSB_UV)
            quantize = '1;
        else
            quantize = BITS'((voltage_uv + (MUTATION == 2 ? 1 : 0)) / LSB_UV);
    endfunction

    assign busy = state != IDLE;
    assign start_ready = rst_n && !busy && !result_valid;

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= IDLE;
            remaining <= '0;
            sampled_code <= '0;
            overrun <= 0;
            result_valid <= 0;
            result_code <= '0;
        end else begin
            overrun <= start && !start_ready;
            if (result_valid && (result_ready || MUTATION == 3))
                result_valid <= 0;

            if (start && (start_ready || MUTATION == 4)) begin
                state <= ACQUIRING;
                remaining <= TIMER_W'(ACQUIRE);
                if (MUTATION == 1)
                    sampled_code <= quantize(vin_uv);
            end else if (busy) begin
                // Both busy states load a positive timer and leave it at one.
                if (remaining != TIMER_W'(1)) begin
                    remaining <= remaining - 1'b1;
                end else if (state == ACQUIRING) begin
                    if (MUTATION != 1)
                        sampled_code <= quantize(vin_uv);
                    state <= CONVERTING;
                    remaining <= TIMER_W'(CONVERT);
                end else begin
                    state <= IDLE;
                    remaining <= '0;
                    result_code <= sampled_code;
                    result_valid <= 1;
                end
            end
        end
    end
endmodule
