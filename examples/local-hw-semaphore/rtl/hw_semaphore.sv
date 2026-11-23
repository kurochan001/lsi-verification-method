// Four lock slots, two counting fences, and two ordered event inputs.
module hw_semaphore #(parameter WIN=8, KMAX=2, MUTATION=0)(
    input wire clk, rst_n, claim, release_req,
    input wire [1:0] slot, inc, rearm, events,
    output reg [3:0] owned,
    output reg grant,
    output reg [1:0] done, passed, suppressed,
    output wire [15:0] counts,
    output reg window_active
);
    reg [7:0] count [0:1];
    assign counts = {count[1], count[0]};
    integer i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            owned <= 0; grant <= 0; done <= 0;
            count[0] <= 0; count[1] <= 0;
        end else begin
            grant <= claim && !owned[slot];
            if (release_req || (MUTATION == 1 && owned[slot])) owned[slot] <= 0;
            else if (claim) owned[slot] <= 1;
            // Release has priority on the same selected slot.
            if (release_req) grant <= 0;
            for (i=0; i<2; i=i+1) begin
                if (rearm[i]) begin count[i] <= 0; done[i] <= 0; end
                else if (inc[i]) begin
                    if (count[i] != 255 || MUTATION == 2) count[i] <= count[i] + 8'd1;
                    if (count[i] == 254) done[i] <= 1;
                    if (count[i] == 255 && MUTATION == 2) done[i] <= 0;
                end
            end
        end
    end

    localparam TIMER_BITS = $clog2(WIN+1), USED_BITS = $clog2(KMAX+1);
    reg [TIMER_BITS-1:0] timer, next_timer;
    reg [USED_BITS-1:0] used, next_used;
    reg next_active;
    reg [1:0] next_pass, next_suppress;
    integer lane;
    always @* begin
        next_timer = timer;
        next_used = used;
        next_active = window_active;
        next_pass = 0;
        next_suppress = 0;
        if (window_active && timer == 0) begin
            next_suppress = events;
            next_active = 0;
            next_used = 0;
        end else begin
            if (window_active) next_timer = timer - 1'b1;
            for (lane=0; lane<2; lane=lane+1) begin
                if (events[lane]) begin
                    next_pass[lane] = 1;
                    if (!next_active) begin
                        next_active = 1;
                        next_used = 0;
                        next_timer = TIMER_BITS'(MUTATION == 3 ? WIN : WIN-1);
                    end
                    next_used = MUTATION == 4 ? 1 : next_used + 1'b1;
                    if (next_used == USED_BITS'(KMAX)) begin
                        next_active = 0;
                        next_used = 0;
                        next_timer = 0;
                    end
                end
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            timer <= 0; used <= 0; window_active <= 0; passed <= 0; suppressed <= 0;
        end else begin
            timer <= next_timer; used <= next_used; window_active <= next_active;
            passed <= next_pass; suppressed <= next_suppress;
        end
    end
endmodule
