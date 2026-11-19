module pwm_adc_trigger #(
    parameter integer HALF_PERIOD = 8,
    parameter integer MUTATION = 0,
    parameter integer LEVEL_W = $clog2(HALF_PERIOD + 1)
)(
    input wire clk, rst_n, enable,
    input wire cfg_valid,
    input wire [LEVEL_W-1:0] cfg_duty, cfg_sample,
    output reg cfg_error,
    output reg [LEVEL_W-1:0] active_duty, active_sample,
    output reg pwm,
    output wire adc_start
);
    localparam [LEVEL_W-1:0] DEFAULT_SAMPLE = LEVEL_W'(HALF_PERIOD / 2);
    reg [LEVEL_W-1:0] shadow_duty, shadow_sample;
    reg [LEVEL_W-1:0] level;
    reg up;

    wire cfg_legal = cfg_duty <= LEVEL_W'(HALF_PERIOD)
                  && cfg_sample != 0 && cfg_sample < LEVEL_W'(HALF_PERIOD);
    wire cfg_write = cfg_valid && cfg_legal;
    wire boundary = up && level == 0;
    wire apply_now = enable && (boundary || MUTATION == 2);
    wire [LEVEL_W-1:0] next_duty = cfg_write && MUTATION != 4 ? cfg_duty : shadow_duty;
    wire [LEVEL_W-1:0] next_sample = cfg_write && MUTATION != 4 ? cfg_sample : shadow_sample;
    wire [LEVEL_W-1:0] event_level = active_sample + LEVEL_W'(MUTATION == 3 ? 1 : 0);
    // The ADC sees this event at the same edge as the matching carrier level.
    assign adc_start = rst_n && (enable || MUTATION == 5) && (up || MUTATION == 1)
                    && level == event_level;

    always @(posedge clk) begin
        if (!rst_n) begin
            level <= '0;
            up <= 1;
            shadow_duty <= '0;
            shadow_sample <= DEFAULT_SAMPLE;
            active_duty <= '0;
            active_sample <= DEFAULT_SAMPLE;
            pwm <= 0;
            cfg_error <= 0;
        end else begin
            cfg_error <= cfg_valid && !cfg_legal;
            if (cfg_write) begin
                shadow_duty <= cfg_duty;
                shadow_sample <= cfg_sample;
            end
            if (!enable) begin
                level <= '0;
                up <= 1;
                pwm <= 0;
            end else begin
                if (apply_now) begin
                    active_duty <= next_duty;
                    active_sample <= next_sample;
                end
                // The crest is included once at level HALF_PERIOD.
                if (up && level == LEVEL_W'(HALF_PERIOD-1)) begin
                    level <= LEVEL_W'(HALF_PERIOD);
                    up <= 0;
                end else if (!up && level == 1) begin
                    level <= '0;
                    up <= 1;
                end else if (up)
                    level <= level + 1'b1;
                else
                    level <= level - 1'b1;
                if (apply_now)
                    pwm <= next_duty == LEVEL_W'(HALF_PERIOD) || level < next_duty;
                else
                    pwm <= active_duty == LEVEL_W'(HALF_PERIOD) || level < active_duty;
            end
        end
    end
endmodule
