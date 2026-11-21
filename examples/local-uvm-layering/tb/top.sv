`timescale 1ns/1ps
`include "uvm_macros.svh"
module top;
  import uvm_pkg::*;import layer_pkg::*;
  bit clk=0;
  int cycle=0,mutation;
  layer_if bus(clk);
  wire [4:0] ack,irq,frame_valid;
  wire [7:0] rdata[5],frame_head[5],frame_len[5],frame_sum[5];
  for(genvar m=0;m<5;m++)begin: variants
    frame_port #(.MUTATION(m)) dut(clk,bus.rst_n,bus.req,bus.write,bus.addr,bus.wdata,bus.alarm,
      ack[m],rdata[m],irq[m],frame_valid[m],frame_head[m],frame_len[m],frame_sum[m]);
  end
  assign bus.ack=ack[mutation];assign bus.rdata=rdata[mutation];assign bus.irq=irq[mutation];
  assign bus.frame_valid=frame_valid[mutation];assign bus.frame_head=frame_head[mutation];
  assign bus.frame_len=frame_len[mutation];assign bus.frame_sum=frame_sum[mutation];
  always #5 clk=!clk;
  // One line per rising edge: the inputs the DUT captures and the outputs it showed before the edge.
  always @(posedge clk) if(bus.recording) begin
    cycle<=cycle+1;
    $display("LAYER_SAMPLE %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d %0d",cycle+1,bus.rst_n,bus.req,bus.write,bus.addr,bus.wdata,bus.alarm,
      bus.ack,bus.rdata,bus.irq,bus.frame_valid,bus.frame_head,bus.frame_len,bus.frame_sum);
  end
  initial begin
    string wave;fatal_to_exit catcher;
    bus.rst_n=0;bus.req=0;bus.write=0;bus.addr=0;bus.wdata=0;bus.alarm=0;bus.recording=0;
    if(!$value$plusargs("MUTATION=%d",mutation) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"missing run arguments");
    if(mutation<0 || mutation>4)$fatal(1,"invalid mutation");
    $dumpfile(wave);$dumpvars(0,top);catcher=new;uvm_report_cb::add(null,catcher);
    uvm_config_db#(virtual layer_if)::set(null,"uvm_test_top","bus",bus);
    run_test("layer_test");
  end
  initial begin #20000000;$fatal(1,"layering watchdog");end
endmodule
