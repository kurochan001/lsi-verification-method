// APB-style slave: 0x0000-0x00ff memory, 0x1000-0x101f timer, anything else a bus error.
// WAIT adds that many cycles with pready low in every access phase.
// timer_expire is an observation port for the bench: it is high on the edge where the
// timer expires.
module periph_sys #(parameter WAIT = 0, MUTATION = 0) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        psel,
    input  wire        penable,
    input  wire        pwrite,
    input  wire [15:0] paddr,
    input  wire [31:0] pwdata,
    output wire [31:0] prdata,
    output wire        pready,
    output wire        pslverr,
    output wire        irq,
    output wire        timer_expire
);
    localparam [1:0] WAIT_CYCLES = WAIT[1:0];
    reg [1:0] wait_q;
    wire access = psel && penable;
    assign pready = access && wait_q == WAIT_CYCLES;
    wire done = access && pready;

    always @(posedge clk) begin
        if (!rst_n || !access || pready) wait_q <= 2'd0;
        else wait_q <= wait_q + 2'd1;
    end

    wire sram_sel = paddr[15:8] == 8'h00;
    wire timer_sel = paddr[15:5] == 11'h080;
    wire aligned = paddr[1:0] == 2'b00;
    wire timer_hit;
    // Mutation 4: an unmapped address completes without an error.
    wire error = !aligned || (timer_sel && !timer_hit) ||
                 (!sram_sel && !timer_sel && MUTATION != 4);
    wire write = done && pwrite && !error;
    wire [31:0] sram_rdata;
    wire [31:0] timer_rdata;

    assign pslverr = done && error;
    assign prdata = !done || error ? 32'd0 : sram_sel ? sram_rdata : timer_sel ? timer_rdata : 32'd0;

    irq_timer #(.MUTATION(MUTATION)) timer (
        .clk(clk), .rst_n(rst_n), .wr(write && timer_sel), .addr(paddr[4:2]), .wdata(pwdata[15:0]),
        .rdata(timer_rdata), .hit(timer_hit), .irq(irq), .expire(timer_expire));

    periph_sram #(.MUTATION(MUTATION)) sram (
        .clk(clk), .rst_n(rst_n), .we(write && sram_sel), .index(paddr[7:2]), .wdata(pwdata),
        .rdata(sram_rdata));
endmodule
