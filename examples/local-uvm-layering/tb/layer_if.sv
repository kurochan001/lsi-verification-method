`timescale 1ns/1ps
// The testbench drives at the falling edge and reads at the falling edge.
// tap_* are registered copies of what the DUT captured at the last rising edge,
// so monitors never read a signal in the time step in which a driver changes it.
interface layer_if(input bit clk);
  logic rst_n,req,write,alarm;
  logic [2:0] addr;
  logic [7:0] wdata;
  logic ack,irq,frame_valid;
  logic [7:0] rdata,frame_head,frame_len,frame_sum;
  logic tap_req,tap_write,tap_irq;
  logic [2:0] tap_addr;
  logic [7:0] tap_wdata;
  bit recording;
  always @(posedge clk) begin
    tap_req<=rst_n && req;tap_write<=write;tap_addr<=addr;tap_wdata<=wdata;tap_irq<=irq;
  end
endinterface
