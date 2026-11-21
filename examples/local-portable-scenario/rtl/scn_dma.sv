// Two-channel word copy engine of the portable scenario example. Each channel has SRC, DST and
// LEN (word indices into a 256-word memory, 1 to 16 words) and a CTRL/STATUS register; a write
// of 1 to CTRL starts the channel when it is idle. A copy that would read or write past word
// 255, or whose length is 0 or above 16, is refused: the channel reports an error and moves
// nothing. The engine moves one word at a time (a read, then a write) and serves the busy
// channels in turn. Each completion, good or refused, sets the channel's bit of IRQ_PEND
// (write 1 to clear) and its interrupt line.
//
// Register map (byte offsets): channel c at 0x10*c: 0x0 SRC, 0x4 DST, 0x8 LEN, 0xC CTRL/STATUS
// (bit 0 busy, bit 1 error, bits 12..8 words moved). 0x20 IRQ_PEND. Reads have no side effect.
//
// Mutations: 1 finishes one word early, 2 does not check the end of the destination, 3 clears
// every pending bit on any acknowledge, 4 makes channel 1 read from its destination.
module scn_dma #(parameter MUTATION = 0) (
    input  wire        clk, rst_n,
    input  wire        reg_valid, reg_we,
    input  wire [7:0]  reg_addr,
    input  wire [31:0] reg_wdata,
    output reg  [31:0] reg_rdata,
    output wire        mem_valid, mem_we,
    output wire [7:0]  mem_addr,
    output wire [31:0] mem_wdata,
    input  wire [31:0] mem_rdata,
    input  wire        mem_ready,
    output wire [1:0]  irq,
    output wire [1:0]  busy_out
);
    reg [7:0] src0, src1, dst0, dst1;
    reg [4:0] len0, len1, moved0, moved1;
    reg [1:0] busy, err, pend;
    reg inflight, phase, cur, last;
    reg [31:0] data;

    wire [7:0] c_src = cur ? (MUTATION == 4 ? dst1 : src1) : src0;
    wire [7:0] c_dst = cur ? dst1 : dst0;
    wire [4:0] c_len = cur ? len1 : len0;
    wire [4:0] c_moved = cur ? moved1 : moved0;
    wire [4:0] moved_next = c_moved + 5'd1;
    wire last_word = (MUTATION == 1 && c_len > 5'd1) ? moved_next == c_len - 5'd1 : moved_next == c_len;

    assign mem_valid = inflight;
    assign mem_we = inflight && phase;
    assign mem_addr = phase ? c_dst + {3'd0, c_moved} : c_src + {3'd0, c_moved};
    assign mem_wdata = data;
    assign irq = pend;
    assign busy_out = busy;

    // A start of channel c is refused when the copy would not fit.
    function automatic refused(input [7:0] s, input [7:0] d, input [4:0] n);
        refused = n == 5'd0 || n > 5'd16 || {1'b0, s} + {4'd0, n} > 9'd256 ||
                  (MUTATION != 2 && {1'b0, d} + {4'd0, n} > 9'd256);
    endfunction

    wire write = reg_valid && reg_we;
    wire chan_reg = reg_addr[7:5] == 3'd0;
    wire start0 = write && chan_reg && !reg_addr[4] && reg_addr[3:0] == 4'hC && reg_wdata[0] && !busy[0];
    wire start1 = write && chan_reg && reg_addr[4] && reg_addr[3:0] == 4'hC && reg_wdata[0] && !busy[1];
    wire ack = write && reg_addr == 8'h20;
    wire done_word = inflight && phase && mem_ready;
    wire [1:0] finish = done_word && last_word ? (cur ? 2'b10 : 2'b01) : 2'b00;
    wire bad0 = refused(src0, dst0, len0), bad1 = refused(src1, dst1, len1);
    wire [1:0] refuse = {start1 && bad1, start0 && bad0};
    wire [1:0] clear = ack ? (MUTATION == 3 ? 2'b11 : reg_wdata[1:0]) : 2'b00;

    always @(posedge clk) begin
        if (!rst_n) begin
            src0 <= 0; src1 <= 0; dst0 <= 0; dst1 <= 0; len0 <= 0; len1 <= 0;
            moved0 <= 0; moved1 <= 0; busy <= 0; err <= 0; pend <= 0;
            inflight <= 0; phase <= 0; cur <= 0; last <= 1; data <= 0;
        end else begin
            if (write && chan_reg && !reg_addr[4] && !busy[0]) begin
                if (reg_addr[3:0] == 4'h0) src0 <= reg_wdata[7:0];
                if (reg_addr[3:0] == 4'h4) dst0 <= reg_wdata[7:0];
                if (reg_addr[3:0] == 4'h8) len0 <= reg_wdata[4:0];
            end
            if (write && chan_reg && reg_addr[4] && !busy[1]) begin
                if (reg_addr[3:0] == 4'h0) src1 <= reg_wdata[7:0];
                if (reg_addr[3:0] == 4'h4) dst1 <= reg_wdata[7:0];
                if (reg_addr[3:0] == 4'h8) len1 <= reg_wdata[4:0];
            end
            if (start0) begin moved0 <= 0; err[0] <= bad0; busy[0] <= !bad0; end
            if (start1) begin moved1 <= 0; err[1] <= bad1; busy[1] <= !bad1; end
            // Engine: pick the next busy channel in turn, read, then write.
            if (!inflight) begin
                if (busy[!last]) begin inflight <= 1; cur <= !last; phase <= 0; end
                else if (busy[last]) begin inflight <= 1; cur <= last; phase <= 0; end
            end else if (!phase) begin
                if (mem_ready) begin data <= mem_rdata; phase <= 1; end
            end else if (mem_ready) begin
                inflight <= 0; phase <= 0; last <= cur;
                if (cur) moved1 <= moved_next; else moved0 <= moved_next;
                if (last_word) busy[cur] <= 0;
            end
            pend <= (pend & ~clear) | finish | refuse;
        end
    end

    always @* begin
        reg_rdata = 32'd0;
        case (reg_addr)
            8'h00: reg_rdata = {24'd0, src0};
            8'h04: reg_rdata = {24'd0, dst0};
            8'h08: reg_rdata = {27'd0, len0};
            8'h0C: reg_rdata = {19'd0, moved0, 6'd0, err[0], busy[0]};
            8'h10: reg_rdata = {24'd0, src1};
            8'h14: reg_rdata = {24'd0, dst1};
            8'h18: reg_rdata = {27'd0, len1};
            8'h1C: reg_rdata = {19'd0, moved1, 6'd0, err[1], busy[1]};
            8'h20: reg_rdata = {30'd0, pend};
            default: reg_rdata = 32'd0;
        endcase
    end
    /* verilator lint_off UNUSEDSIGNAL */
    wire unused = &{1'b0, reg_wdata[31:8]};
    /* verilator lint_on UNUSEDSIGNAL */
endmodule
