// Proof harness. The reference is one full-width addition applied to the design's own count,
// so each step is compared for every count value and every input, without counting up to it.
// FUNCTIONAL = 1 keeps test_mode low: the proof then covers the counter without its test path,
// and a bounded check from reset can no longer jump to a distant carry.
module long_counter_formal #(parameter WIDTH = 32, SPLIT = 16, MUTATION = 0, FUNCTIONAL = 0) (
    input wire clk, rst_n, enable, clear, test_mode, test_load,
    input wire [WIDTH-1:0] limit, test_value
);
    wire [WIDTH-1:0] count;
    wire tick;
    long_counter #(.WIDTH(WIDTH), .SPLIT(SPLIT), .MUTATION(MUTATION)) dut(
        .clk(clk), .rst_n(rst_n), .enable(enable), .clear(clear), .limit(limit),
        .test_mode(test_mode), .test_load(test_load), .test_value(test_value), .count(count), .tick(tick));

    localparam [WIDTH-1:0] MAX = {WIDTH{1'b1}};
    localparam [WIDTH-1:0] ONE = 1;
    wire load = test_mode && test_load;
    wire step = rst_n && !clear && !load && enable;
    reg f_past = 0;
    reg [WIDTH-1:0] f_count = 0;   // what the specification gives for this cycle
    reg f_tick = 0;
    always @(posedge clk) begin
        f_past <= 1;
        f_tick <= step && count == limit;
        if (!rst_n || clear) f_count <= 0;
        else if (load) f_count <= test_value;
        else if (enable) f_count <= count == limit ? {WIDTH{1'b0}} : count + ONE;
        else f_count <= count;
    end

    generate
        if (FUNCTIONAL != 0) begin : g_functional
            always @(posedge clk) as_functional: assume(!test_mode);
        end
    endgenerate

    always @(posedge clk) begin
        if (!f_past) as_initial_reset: assume(!rst_n);
        if (f_past) begin
            if (!$past(rst_n)) ap_reset: assert(count == 0 && !tick);
            ap_count: assert(count == f_count);
            ap_tick: assert(tick == f_tick);
            cp_wrap: cover(tick && $past(limit) != 0 && $past(limit) != MAX);
            cp_rollover: cover(count == 0 && $past(count) == MAX && $past(step) && !tick);
            cp_low_carry: cover($past(step) && count == ONE << SPLIT);
            cp_stage_carry: cover($past(step) && count == ONE << (SPLIT + 8));
            cp_top_carry: cover($past(step) && count == ONE << (WIDTH - 1));
            cp_pause: cover($past(step) && count == ONE << SPLIT && $past(!enable && rst_n && !clear && !load, 2));
        end
    end
endmodule
