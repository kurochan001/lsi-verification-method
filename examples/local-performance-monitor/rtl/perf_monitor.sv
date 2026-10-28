module perf_monitor #(parameter SLOTS=4, MUTATION=0)(
    input wire clk, rst_n,
    input wire start, stop,
    input wire req_valid,
    input wire [1:0] req_tag,
    output wire req_ready,
    input wire resp_valid,
    input wire [1:0] resp_tag,
    output reg [15:0] total_done,
    output reg [7:0] total_max,
    output reg [15:0] window_done,
    output reg [15:0] window_cycles,
    output reg [7:0] window_max,
    output reg [2:0] active_count,
    output reg error
);
    localparam MAX=4;
    reg outstanding [0:MAX-1];
    reg [7:0] age [0:MAX-1];
    reg window_active;
    reg [7:0] latency;
    wire window_count = window_active && !start;

    assign req_ready = rst_n && req_tag < SLOTS && !outstanding[req_tag];

    always @* begin
        active_count = 0;
        for (integer i = 0; i < SLOTS; i = i + 1) active_count = active_count + outstanding[i];
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            total_done <= 0; total_max <= 0;
            window_done <= 0; window_cycles <= 0; window_max <= 0;
            window_active <= 0; error <= 0;
            for (integer i = 0; i < MAX; i = i + 1) begin outstanding[i] <= 0; age[i] <= 0; end
        end else begin
            for (integer i = 0; i < MAX; i = i + 1)
                if (outstanding[i] && age[i] != 8'hff) age[i] <= age[i] + 1'b1;
            if (start) begin
                if (MUTATION != 3) window_done <= 0;
                window_cycles <= 0; window_max <= 0; window_active <= 1;
            end else begin
                if (window_active) window_cycles <= window_cycles + 1;
                if (stop) window_active <= 0;
            end
            if (resp_valid) begin
                if (resp_tag < SLOTS && outstanding[resp_tag]) begin
                    latency = age[resp_tag] == 8'hff ? 8'hff : age[resp_tag] + 1'b1;
                    if (MUTATION != 4) outstanding[resp_tag] <= 0;
                    total_done <= total_done + 1;
                    if (MUTATION != 1) total_max <= latency[7:0] > total_max ? latency[7:0] : total_max;
                    if (window_count) begin
                        window_done <= window_done + 1;
                        window_max <= latency[7:0] > window_max ? latency[7:0] : window_max;
                    end
                end else if (MUTATION != 2) error <= 1;
            end
            if (req_valid && req_ready) begin
                outstanding[req_tag] <= 1;
                age[req_tag] <= 0;
            end
            if (start) error <= 0;
        end
    end
endmodule
