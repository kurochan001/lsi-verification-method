module rtc #(parameter DIV=4, MUTATION=0)(
    input wire clk, rst_n,
    input wire wr,
    input wire [1:0] ridx,
    input wire [7:0] wdata,
    input wire cap,
    output reg [7:0] rdata,
    output wire [15:0] sec_pin,
    output wire [7:0] sub_pin,
    output wire [7:0] capture_sub,
    output wire irq
);
    // CTRL (R0): [0] en, [1] slew_mode, [2] set (jump-set), [6:4] ADJ signed.
    // ALARM (R1): compares the low seconds byte at a seconds tick; bit1 is W1C;
    // reads return {irq, alarm[7:1]}.  SETSEC (R2, while set=1): loads seconds
    // and clears sub.  CAP (R3): {seconds, sub} latched by a two-flop capture.
    // MUTATION: 1 = the sub wrap loses the seconds carry, 2 = the alarm compares
    // the post-increment seconds, 3 = slew may rewind below the current seconds,
    // 4 = W1C clears even when a new match arrives in the same cycle.
    reg [7:0] sub, alarm, cap_sec, cap_sub;
    reg [6:0] ctrl;
    reg [15:0] sec;
    reg irq_r, cap_meta, cap_s, cap_p;
    wire en = ctrl[0];
    wire slew = ctrl[1];
    wire set = ctrl[2];
    wire [2:0] adj = ctrl[6:4];
    wire [7:0] last = 8'(DIV - 1);
    wire tick = en && sub == last;
    wire fire = cap_s && !cap_p;
    wire signed [15:0] adj_s = {{13{adj[2]}}, adj};
    wire [15:0] inc = !slew ? 16'd1 :
        (MUTATION == 3 || adj_s >= 16'sd0) ? (16'sd1 + adj_s) : 16'd0;
    wire newmatch = tick && alarm != 8'd0 &&
        ((MUTATION == 2 ? sec[7:0] + inc[7:0] : sec[7:0]) == alarm);
    wire w1c = wr && ridx == 2'd1 && wdata[1];

    always @* begin
        rdata = 0;
        if (!wr) case (ridx)
            2'd0: rdata = {1'b0, ctrl};
            2'd1: rdata = {irq_r, alarm[7:1]};
            2'd3: rdata = cap_sec;
            default: rdata = 0;
        endcase
    end

    assign capture_sub = cap_sub;
    assign sec_pin = sec;
    assign sub_pin = sub;
    assign irq = irq_r;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sub <= 0; alarm <= 0; cap_sec <= 0; cap_sub <= 0; ctrl <= 0;
            sec <= 0; irq_r <= 0; cap_meta <= 0; cap_s <= 0; cap_p <= 0;
        end else begin
            if (newmatch)
                irq_r <= MUTATION == 4 && w1c ? 1'b0 : 1'b1;
            else if (w1c)
                irq_r <= 1'b0;
            if (tick && !set && MUTATION != 1)
                sec <= sec + inc;
            if (en)
                sub <= tick ? 8'd0 : sub + 8'd1;
            if (fire) begin
                cap_sec <= sec[7:0];
                cap_sub <= sub;
            end
            if (wr) case (ridx)
                2'd0: ctrl <= wdata[6:0];
                2'd1: alarm <= wdata;
                2'd2: if (set) begin
                    sec <= {8'd0, wdata};
                    sub <= 8'd0;
                end
                default: begin end
            endcase
            cap_p <= cap_s;
            cap_s <= cap_meta;
            cap_meta <= cap;
        end
    end
endmodule
