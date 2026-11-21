// Periodic timer with a pending flag and an interrupt enable.
// Word offsets: 0 LOAD, 1 CTRL {ie, en}, 2 STATUS {overrun, pending} (write 1 to clear),
// 3 COUNT (cycles left before the next expiry), 4 EXPIRED (8-bit count since enable).
// When an acknowledge and an expiry land on the same clock edge, the expiry wins:
// pending stays set, so the new event is not lost.
module irq_timer #(parameter MUTATION = 0) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        wr,
    input  wire [2:0]  addr,
    input  wire [15:0] wdata,
    output reg  [31:0] rdata,
    output wire        hit,
    output wire        irq,
    output wire        expire
);
    reg [15:0] load_q;
    reg [15:0] count_q;
    reg en_q;
    reg ie_q;
    reg pending_q;
    reg overrun_q;
    reg [7:0] expired_q;

    assign hit = addr <= 3'd4;
    assign expire = en_q && count_q == 16'd0;
    wire wr_ctrl = wr && addr == 3'd1;
    wire wr_status = wr && addr == 3'd2;
    wire start = wr_ctrl && wdata[0] && !en_q;
    wire clear_pending = wr_status && wdata[0];
    // Mutation 5: acknowledging pending also clears overrun.
    wire clear_overrun = wr_status && (wdata[1] || (MUTATION == 5 && wdata[0]));
    // Mutation 2: the enable is ignored.
    assign irq = pending_q && (ie_q || MUTATION == 2);

    always @(posedge clk) begin
        if (!rst_n) begin
            load_q <= 16'd0;
            count_q <= 16'd0;
            en_q <= 1'b0;
            ie_q <= 1'b0;
            pending_q <= 1'b0;
            overrun_q <= 1'b0;
            expired_q <= 8'd0;
        end else begin
            if (wr && addr == 3'd0) load_q <= wdata;
            if (wr_ctrl) begin
                en_q <= wdata[0];
                ie_q <= wdata[1];
            end
            if (start || expire) count_q <= load_q;
            else if (en_q) count_q <= count_q - 16'd1;
            // Mutation 1: the acknowledge wins over a same-edge expiry, losing it.
            if (MUTATION == 1) pending_q <= (pending_q || expire) && !clear_pending;
            else pending_q <= expire || (pending_q && !clear_pending);
            overrun_q <= (overrun_q && !clear_overrun) || (expire && pending_q && !clear_pending);
            // Mutation 6: enabling again does not restart EXPIRED.
            if (start && MUTATION != 6) expired_q <= 8'd0;
            else if (expire) expired_q <= expired_q + 8'd1;
        end
    end

    always @* begin
        case (addr)
            3'd0: rdata = {16'd0, load_q};
            3'd1: rdata = {30'd0, ie_q, en_q};
            3'd2: rdata = {30'd0, overrun_q, pending_q};
            3'd3: rdata = {16'd0, count_q};
            3'd4: rdata = {24'd0, expired_q};
            default: rdata = 32'd0;
        endcase
    end
endmodule
