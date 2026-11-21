// Wishbone B4 classic (standard, single-cycle) slave to APB4 master bridge.
// One Wishbone transfer becomes one APB transfer. A cycle the master abandons
// (CYC low) still completes on APB, but gets no response on Wishbone.
module wb_apb_bridge #(
    parameter AW = 16,
    parameter MUTATION = 0
) (
    input             clk,
    input             rst_n,
    // Wishbone slave side
    input             cyc_i,
    input             stb_i,
    input             we_i,
    input  [AW-1:0]   adr_i,
    input  [31:0]     dat_i,
    input  [3:0]      sel_i,
    output            ack_o,
    output            err_o,
    output [31:0]     dat_o,
    // APB master side
    output            psel,
    output            penable,
    output            pwrite,
    output [AW-1:0]   paddr,
    output [31:0]     pwdata,
    output [3:0]      pstrb,
    input             pready,
    input             pslverr,
    input  [31:0]     prdata
);
    localparam [1:0] IDLE = 2'd0, SETUP = 2'd1, ACCESS = 2'd2, RESP = 2'd3;

    reg [1:0]    state;
    reg          we_q;
    reg [AW-1:0] adr_q;
    reg [31:0]   dat_q;
    reg [3:0]    sel_q;
    reg [31:0]   rdata_q;
    reg          err_q;
    reg          cancel_q;

    wire request = cyc_i && stb_i;
    // The master leaving the cycle in this clock counts as well as an earlier one.
    wire abandoned = cancel_q || !cyc_i;
    wire done = MUTATION == 7 ? 1'b1 : pready;

    always @(posedge clk) begin
        if (!rst_n) begin
            state    <= IDLE;
            we_q     <= 1'b0;
            adr_q    <= {AW{1'b0}};
            dat_q    <= 32'd0;
            sel_q    <= 4'd0;
            rdata_q  <= 32'd0;
            err_q    <= 1'b0;
            cancel_q <= 1'b0;
        end else begin
            case (state)
                IDLE: if (request) begin
                    we_q  <= we_i;
                    adr_q <= adr_i;
                    dat_q <= dat_i;
                    sel_q <= sel_i;
                    if (MUTATION != 9) cancel_q <= 1'b0;
                    state <= SETUP;
                end
                SETUP: begin
                    if (!cyc_i) cancel_q <= 1'b1;
                    state <= ACCESS;
                end
                ACCESS: begin
                    if (!cyc_i) cancel_q <= 1'b1;
                    if (done) begin
                        rdata_q <= prdata;
                        err_q   <= pslverr;
                        state   <= (abandoned && MUTATION != 1) ? IDLE : RESP;
                    end
                end
                default: begin
                    if (MUTATION == 8 && request) begin
                        we_q  <= we_i;
                        adr_q <= adr_i;
                        dat_q <= dat_i;
                        sel_q <= sel_i;
                        state <= SETUP;
                    end else begin
                        state <= IDLE;
                    end
                end
            endcase
        end
    end

    wire busy = state == SETUP || state == ACCESS;
    wire [3:0] rmask = MUTATION == 6 ? 4'hf : sel_q;
    wire [31:0] masked = rdata_q & {{8{rmask[3]}}, {8{rmask[2]}}, {8{rmask[1]}}, {8{rmask[0]}}};
    wire respond = state == RESP && request;
    wire failed = MUTATION == 5 ? 1'b0 : err_q;

    assign psel    = busy;
    assign penable = MUTATION == 2 ? busy : state == ACCESS;
    assign pwrite  = busy && we_q;
    assign paddr   = !busy ? {AW{1'b0}} : (MUTATION == 4 ? adr_i : adr_q);
    assign pwdata  = busy && we_q ? dat_q : 32'd0;
    assign pstrb   = busy && (we_q || MUTATION == 3) ? sel_q : 4'd0;
    assign ack_o   = respond && !failed;
    assign err_o   = respond && failed;
    assign dat_o   = ack_o && !we_q ? masked : 32'd0;
endmodule
