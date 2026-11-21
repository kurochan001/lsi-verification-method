// Teaching register bank with a small memory: APB3 signal subset, no wait states,
// synchronous active-low reset. Addresses are byte addresses, one 32-bit word each.
//   0x00 CTRL    RW  [7:0], reset 0xA5, upper bits read as zero
//   0x04 ID      RO  constant; writes are accepted and ignored
//   0x08 STATUS  RO  [7:0] cycle counter since reset (volatile)
//   0x0C IRQ     W1C [3:0], set by the events input; an event wins over a clear
//   0x10 SCRATCH RW  [31:0], reset 0
//   0x14 CMD     WO  [0], reads as zero; writing 1 returns CTRL, IRQ and SCRATCH
//                    to their reset values (STATUS and the memory are not affected)
//   0x40-0x7C    16-word memory, RW, not reset
// Every other address answers with pslverr and changes nothing.
module reg_bank #(
  parameter integer MUTATION = 0
) (
  input wire clk,
  input wire rst_n,
  input wire psel,
  input wire penable,
  input wire pwrite,
  input wire [7:0] paddr,
  input wire [31:0] pwdata,
  input wire [3:0] events,
  output wire pready,
  output wire pslverr,
  output reg [31:0] prdata
);
  localparam [31:0] ID_VALUE = 32'h5247_5351;
  // Mutation 1: wrong reset value of CTRL.
  localparam [7:0] CTRL_RESET = MUTATION == 1 ? 8'hA4 : 8'hA5;

  reg [7:0] ctrl;
  reg [7:0] status;
  reg [3:0] irq;
  reg [31:0] scratch;
  reg id_low;
  reg [31:0] mem [0:15];

  wire access = psel && penable;
  wire write = access && pwrite;
  // Mutation 6: 0x90 is an unintended alias of SCRATCH (address bit 7 ignored).
  wire [7:0] addr = (MUTATION == 6 && paddr == 8'h90) ? 8'h10 : paddr;
  wire is_mem = addr[7:6] == 2'b01 && addr[1:0] == 2'b00;
  wire is_reg = addr <= 8'h14 && addr[1:0] == 2'b00;
  wire [3:0] word = addr[5:2];
  // Mutation 4 drops one address bit on writes only; mutation 9 drops it on reads
  // as well, so words n and n+8 are one consistent word.
  wire [3:0] write_word = (MUTATION == 4 || MUTATION == 9) ? {1'b0, word[2:0]} : word;
  wire [3:0] read_word = MUTATION == 9 ? {1'b0, word[2:0]} : word;
  wire [3:0] clear = (write && addr == 8'h0C) ? pwdata[3:0] : 4'b0000;
  // Mutation 7: IRQ bit 2 is never cleared by a write.
  wire [3:0] clear_used = MUTATION == 7 ? (clear & 4'b1011) : clear;
  wire soft_reset = write && addr == 8'h14 && pwdata[0];

  assign pready = access;
  assign pslverr = access && !is_mem && !is_reg;

  always @* begin
    prdata = 32'b0;
    if (is_mem) prdata = mem[read_word];
    else case (addr)
      8'h00: prdata = {24'b0, ctrl};
      8'h04: prdata = {ID_VALUE[31:1], id_low};
      8'h08: prdata = {24'b0, status};
      8'h0C: prdata = {28'b0, irq};
      8'h10: prdata = scratch;
      default: prdata = 32'b0;
    endcase
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      ctrl <= CTRL_RESET;
      status <= 8'b0;
      irq <= 4'b0;
      scratch <= 32'b0;
      id_low <= ID_VALUE[0];
    end else begin
      status <= status + 8'd1;
      irq <= (irq & ~clear_used) | events;
      if (write && addr == 8'h00) ctrl <= pwdata[7:0];
      if (write && addr == 8'h10) begin
        // Mutation 2: bit 7 of SCRATCH stores bit 6 of the written word.
        scratch <= MUTATION == 2 ? {pwdata[31:8], pwdata[6], pwdata[6:0]} : pwdata;
        // Mutation 5: a write to SCRATCH also clears CTRL bit 0.
        if (MUTATION == 5) ctrl[0] <= 1'b0;
      end
      // Mutation 3: bit 0 of the read-only ID can be written.
      if (MUTATION == 3 && write && addr == 8'h04) id_low <= pwdata[0];
      if (soft_reset) begin
        ctrl <= CTRL_RESET;
        irq <= 4'b0;
        scratch <= 32'b0;
      end
    end
  end

  always @(posedge clk) begin
    if (write && is_mem) begin
      // Mutation 8: bit 31 of word 3 cannot be set.
      mem[write_word] <= (MUTATION == 8 && write_word == 4'd3) ? (pwdata & 32'h7FFF_FFFF) : pwdata;
    end
  end
endmodule
