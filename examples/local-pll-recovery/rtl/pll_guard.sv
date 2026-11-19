module pll_guard #(
    parameter integer LOCK_CYCLES = 5,
    parameter integer TIMEOUT = 24,
    parameter integer MUTATION = 0
)(
    input wire aon_clk, pll_clk, arst_n, pll_locked,
    output reg clock_permit,
    output reg clock_missing,
    output wire work_reset_n
);
    localparam integer LOCK_W = $clog2(LOCK_CYCLES+1);
    localparam integer TIMER_W = $clog2(TIMEOUT+1);
    localparam [LOCK_W-1:0] LOCK_LIMIT = LOCK_W'(LOCK_CYCLES);
    localparam [TIMER_W-1:0] TIME_LIMIT = TIMER_W'(TIMEOUT);

    (* ASYNC_REG = "TRUE" *) reg aon_release_first, aon_reset_n;
    (* ASYNC_REG = "TRUE" *) reg pll_release_first, monitor_reset_n;
    (* ASYNC_REG = "TRUE" *) reg [1:0] lock_sync, probe_sync, ack_sync, release_sync;
    reg probe, ack;
    reg [LOCK_W-1:0] lock_count;
    reg [TIMER_W-1:0] age;
    reg seen_response;
    wire qualified_lock = MUTATION == 1 ? lock_sync[1] :
                          ((lock_sync[1] || MUTATION == 2) && lock_count == LOCK_LIMIT);
    wire ack_received = ack_sync[1] == probe;
    wire clock_alive = !clock_missing && (age != TIME_LIMIT - 1'b1 || ack_received);

    always @(posedge aon_clk or negedge arst_n) begin
        if (!arst_n) begin
            aon_release_first <= 0;
            aon_reset_n <= 0;
        end else begin
            aon_release_first <= 1;
            aon_reset_n <= aon_release_first;
        end
    end

    always @(posedge pll_clk or negedge arst_n) begin
        if (!arst_n) begin
            pll_release_first <= 0;
            monitor_reset_n <= 0;
        end else begin
            pll_release_first <= 1;
            monitor_reset_n <= pll_release_first;
        end
    end

    // At most one probe is in flight. A fast PLL cannot alias a free-running toggle.
    // This observer uses system reset, so it can reply while the workload is in reset.
    always @(posedge pll_clk or negedge monitor_reset_n) begin
        if (!monitor_reset_n) begin
            probe_sync <= '0;
            ack <= 0;
        end else begin
            probe_sync <= {probe_sync[0], probe};
            ack <= probe_sync[1];
        end
    end

    always @(posedge aon_clk or negedge aon_reset_n) begin
        if (!aon_reset_n) begin
            lock_sync <= '0;
            ack_sync <= '0;
            probe <= 1;
            lock_count <= '0;
            age <= '0;
            seen_response <= 0;
            clock_missing <= 0;
            clock_permit <= 0;
        end else begin
            lock_sync <= {lock_sync[0], pll_locked};
            ack_sync <= {ack_sync[0], ack};
            if (!lock_sync[1]) begin
                if (MUTATION != 2 || lock_count != LOCK_LIMIT)
                    lock_count <= '0;
            end else if (lock_count != LOCK_LIMIT)
                lock_count <= lock_count + 1'b1;

            if (ack_received) begin
                probe <= ~probe;
                age <= '0;
                seen_response <= 1;
                clock_missing <= 0;
            end else if (age < TIME_LIMIT) begin
                age <= age + 1'b1;
                if (age == TIME_LIMIT - 1'b1)
                    clock_missing <= 1;
            end

            clock_permit <= qualified_lock && seen_response && (clock_alive || MUTATION == 3);
        end
    end

    // AON can assert reset without a PLL edge. Only PLL edges release it.
    always @(posedge pll_clk or negedge clock_permit) begin
        if (!clock_permit)
            release_sync <= '0;
        else
            release_sync <= {release_sync[0], 1'b1};
    end

    assign work_reset_n = MUTATION == 4 ? clock_permit : release_sync[1];
endmodule
