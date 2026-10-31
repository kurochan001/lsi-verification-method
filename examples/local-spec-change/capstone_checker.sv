`timescale 1ns/1ps
module capstone_checker #(parameter REVISION=1)(
  input wire clk,rst_n,psel,penable,pwrite,pready,pslverr,
  input wire [7:0] paddr,input wire [31:0] pwdata,config_value,
  input wire [3:0] events,pending,input wire irq
);
  bit history=0;int off,expected_revision;
  wire [3:0] clear_mask=(psel && penable && pready && !pslverr && pwrite && paddr==8) ? pwdata[3:0]:0;
  function automatic bit next_bit(bit prior,bit event_bit,bit clear_bit);
    case({event_bit,clear_bit})
      2'b00:return prior;
      2'b01:return 0;
      2'b10:return 1;
      2'b11:return expected_revision==1;
    endcase
  endfunction
  initial begin
    expected_revision=REVISION;
    void'($value$plusargs("CAP_SVA_OFF=%d",off));void'($value$plusargs("CAP_EXPECTED_REV=%d",expected_revision));
  end
  always @(posedge clk)history<=1;
  for(genvar b=0;b<4;b++)begin: bit_check
    ap_update:assert property(@(posedge clk) disable iff(off!=0 || !history)
      pending[b]==($past(rst_n) ? next_bit($past(pending[b]),$past(events[b]),$past(clear_mask[b])):1'b0))
      else begin $display("CHECK_FAIL CAP_PRIORITY");$fatal(1,"priority or reset update differs");end
  end
  ap_irq:assert property(@(posedge clk) disable iff(off!=0) irq==|(pending & config_value[3:0]))
    else begin $display("CHECK_FAIL CAP_IRQ");$fatal(1,"IRQ equation differs");end
  cp_collision0:cover property(@(posedge clk) off==0 && rst_n && clear_mask[0] && events[0])$display("CAP_COVER cp_collision0");
  cp_collision1:cover property(@(posedge clk) off==0 && rst_n && clear_mask[1] && events[1])$display("CAP_COVER cp_collision1");
  cp_collision2:cover property(@(posedge clk) off==0 && rst_n && clear_mask[2] && events[2])$display("CAP_COVER cp_collision2");
  cp_collision3:cover property(@(posedge clk) off==0 && rst_n && clear_mask[3] && events[3])$display("CAP_COVER cp_collision3");
  cp_reset:cover property(@(posedge clk) off==0 && history && $past(!rst_n) && pending==0)$display("CAP_COVER cp_reset");
  cp_masked:cover property(@(posedge clk) off==0 && rst_n && |(pending & ~config_value[3:0]))$display("CAP_COVER cp_masked");
  cp_unmasked:cover property(@(posedge clk) off==0 && rst_n && irq)$display("CAP_COVER cp_unmasked");
endmodule
