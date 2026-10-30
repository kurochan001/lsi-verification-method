// SoC integration top: eight blocks, the interrupt map, the pin multiplexer and one
// register stage toward the CPU. Only the wiring here is under test; the blocks are
// verified on their own and appear as port-only black boxes in the formal check.
module soc_top #(parameter MUTATION = 0) (
    input  wire       clk, rst_ni,
    input  wire [3:0] pad_i,
    output wire [3:0] pad_o, pad_oe,
    output reg        cpu_irq);
    wire rst_n;
    wire [1:0] pinmux;
    wire debug_en, timer_irq, uart_tx, uart_irq, uart_req, gpio_irq, dma_irq, dma_err, tdo, irq;
    wire [3:0] gpio_o, gpio_oe;
    // Mutation 1 swaps the timer and UART interrupt lines.
    wire [7:0] irq_src = MUTATION == 1 ? {2'b00, dma_err, dma_irq, gpio_irq, timer_irq, uart_irq, 1'b0}
                                       : {2'b00, dma_err, dma_irq, gpio_irq, uart_irq, timer_irq, 1'b0};
    // An unrouted receiver must see the idle level; mutation 2 ties it low.
    wire uart_rx = pinmux[1] ? pad_i[1] : MUTATION != 2;
    wire tdi = debug_en && pad_i[2];

    rst_sync u_rst(.clk_i(clk), .rst_ni(rst_ni), .rst_no(rst_n));
    sys_ctrl u_sys(.clk_i(clk), .rst_ni(rst_n), .pinmux_o(pinmux), .debug_en_o(debug_en));
    timer    u_timer(.clk_i(clk), .rst_ni(rst_n), .irq_o(timer_irq));
    uart     u_uart(.clk_i(clk), .rst_ni(rst_n), .rx_i(uart_rx), .tx_o(uart_tx), .irq_o(uart_irq),
                    .dma_req_o(uart_req));
    gpio     u_gpio(.clk_i(clk), .rst_ni(rst_n), .gpio_i(pad_i), .gpio_o(gpio_o), .gpio_oe_o(gpio_oe),
                    .irq_o(gpio_irq));
    // Mutation 4 resets the DMA from the raw pad reset instead of the synchronized one.
    dma      u_dma(.clk_i(clk), .rst_ni(MUTATION == 4 ? rst_ni : rst_n), .req_i({3'b000, uart_req}),
                   .irq_o(dma_irq), .err_o(dma_err));
    dbg_port u_dbg(.clk_i(clk), .rst_ni(rst_n), .tdi_i(tdi), .tdo_o(tdo));
    irq_ctrl u_irq(.clk_i(clk), .rst_ni(rst_n), .src_i(irq_src), .irq_o(irq));

    // Pad 0: UART TX or GPIO. Pad 1: UART RX (input only) or GPIO.
    // Pads 2 and 3: debug TDI (input) and TDO while debug is enabled, GPIO otherwise.
    // Mutation 3 lets TDO reach pad 3 even with debug disabled.
    assign pad_o  = {debug_en || MUTATION == 3 ? tdo : gpio_o[3], gpio_o[2] && !debug_en,
                     gpio_o[1] && !pinmux[1], pinmux[0] ? uart_tx : gpio_o[0]};
    assign pad_oe = {debug_en || gpio_oe[3], gpio_oe[2] && !debug_en,
                     gpio_oe[1] && !pinmux[1], pinmux[0] || gpio_oe[0]};

    always @(posedge clk) cpu_irq <= rst_n && irq;
endmodule
