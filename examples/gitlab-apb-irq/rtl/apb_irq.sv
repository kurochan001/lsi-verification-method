// Integration of the existing APB register block with four interrupt sources.
module apb_irq #(
  parameter integer WAIT_CYCLES = 0,
  parameter integer MUTATION = 0
) (
  input wire clk, rst_n, psel, penable, pwrite,
  input wire [7:0] paddr,
  input wire [31:0] pwdata,
  input wire [3:0] events,
  output wire pready, pslverr,
  output wire [31:0] prdata, config_value,
  output wire [3:0] pending,
  output wire irq
);
  wire [3:0] delivered_events = MUTATION == 1 ? events & config_value[3:0] : events;
  wire active_irq = |(pending & config_value[3:0]);
  reg sticky_irq;
  apb_regs #(.WAIT_CYCLES(WAIT_CYCLES), .MUTATION(0)) regs (
    clk, rst_n, psel, penable, pwrite, paddr, pwdata, delivered_events,
    pready, pslverr, prdata, config_value, pending
  );
  // Intentional integration defects: mask event storage, bypass the mask,
  // or retain an interrupt after its source has been cleared.
  assign irq = MUTATION == 2 ? |pending :
               MUTATION == 3 ? active_irq | sticky_irq : active_irq;
  always @(posedge clk) begin
    if (!rst_n) sticky_irq <= 0;
    else if (active_irq) sticky_irq <= 1;
  end
endmodule
