// Port-only stand-ins for the integrated blocks. Every output is a fresh free value in
// every cycle, so the connectivity proof holds whatever the blocks themselves do.
// The ports match the block interfaces that soc_top instantiates.
module rst_sync(input wire clk_i, rst_ni, output wire rst_no);
    (* anyseq *) wire free; assign rst_no = free;
endmodule
module sys_ctrl(input wire clk_i, rst_ni, output wire [1:0] pinmux_o, output wire debug_en_o);
    (* anyseq *) wire [2:0] free; assign {debug_en_o, pinmux_o} = free;
endmodule
module timer(input wire clk_i, rst_ni, output wire irq_o);
    (* anyseq *) wire free; assign irq_o = free;
endmodule
module uart(input wire clk_i, rst_ni, rx_i, output wire tx_o, irq_o, dma_req_o);
    (* anyseq *) wire [2:0] free; assign {dma_req_o, irq_o, tx_o} = free;
endmodule
module gpio(input wire clk_i, rst_ni, input wire [3:0] gpio_i, output wire [3:0] gpio_o, gpio_oe_o,
            output wire irq_o);
    (* anyseq *) wire [8:0] free; assign {irq_o, gpio_oe_o, gpio_o} = free;
endmodule
module dma(input wire clk_i, rst_ni, input wire [3:0] req_i, output wire irq_o, err_o);
    (* anyseq *) wire [1:0] free; assign {err_o, irq_o} = free;
endmodule
module dbg_port(input wire clk_i, rst_ni, tdi_i, output wire tdo_o);
    (* anyseq *) wire free; assign tdo_o = free;
endmodule
module irq_ctrl(input wire clk_i, rst_ni, input wire [7:0] src_i, output wire irq_o);
    (* anyseq *) wire free; assign irq_o = free;
endmodule
