`timescale 1ns/1ps
`include "uvm_macros.svh"
module top;
  import uvm_pkg::*;import uvm_apb_pkg::*;import coord_pkg::*;
  bit clk=0,history=0;
  bit [7:0] tick=0;
  apb_if bus(clk);stream_if stream(clk);
  int mutation,sva_off,sva_fault;
  wire [3:0] input_ready,output_valid;
  wire [7:0] outputs[4];
  wire gain_write=bus.psel && bus.penable && bus.pready && !bus.pslverr && bus.pwrite && bus.paddr==0;
  apb_regs #(.WAIT_CYCLES(0),.MUTATION(0)) registers(
    clk,bus.rst_n,bus.psel,bus.penable,bus.pwrite,bus.paddr,bus.pwdata,bus.events,
    bus.pready,bus.pslverr,bus.prdata,bus.config_value,bus.pending);
  for(genvar m=0;m<4;m++)begin: variants
    gain_pipe #(.MUTATION(m)) dut(clk,bus.rst_n,stream.input_valid,stream.output_ready,
      stream.input_data,bus.config_value[7:0],bus.pwdata[7:0],gain_write,
      input_ready[m],output_valid[m],outputs[m]);
  end
  assign stream.input_ready=input_ready[mutation];assign stream.output_valid=output_valid[mutation];assign stream.output_data=outputs[mutation];
  wire [7:0] checked_data=stream.output_data ^ ((sva_fault && stream.output_valid && !stream.output_ready) ? tick:8'b0);
  ap_stability:assert property(@(posedge clk) disable iff(!bus.rst_n || !stream.recording || sva_off)
    (stream.output_valid && !stream.output_ready) |=> (stream.output_valid && $stable(checked_data)))
    else begin $display("CHECK_FAIL COORD_STABILITY");`uvm_fatal("COORD_STABILITY","output changed while stalled") end
  cp_overlap:cover property(@(posedge clk) !sva_off && stream.recording && bus.rst_n && gain_write && stream.input_valid && stream.input_ready)
    $display("COORD_COVER cp_overlap");
  cp_stall:cover property(@(posedge clk) !sva_off && stream.recording && bus.rst_n && stream.output_valid && !stream.output_ready)
    $display("COORD_COVER cp_stall");
  cp_reset_pending:cover property(@(posedge clk) !sva_off && stream.recording && !bus.rst_n && stream.output_valid)
    $display("COORD_COVER cp_reset_pending");
  cp_reset_done:cover property(@(posedge clk) !sva_off && stream.recording && history &&
    $past(!sva_off && stream.recording && !bus.rst_n && stream.output_valid) && !stream.output_valid)
    $display("COORD_COVER cp_reset_done");
  always #5 clk=!clk;
  always @(posedge clk)begin history<=1;tick<=tick+1;end
  initial begin
    string wave;fatal_to_exit catcher;
    bus.rst_n=0;bus.psel=0;bus.penable=0;bus.pwrite=0;bus.paddr=0;bus.pwdata=0;bus.events=0;
    stream.input_valid=0;stream.input_data=0;stream.output_ready=1;
    if(!$value$plusargs("MUTATION=%d",mutation) || !$value$plusargs("WAVE=%s",wave))$fatal(1,"missing run arguments");
    if(mutation<0 || mutation>3)$fatal(1,"invalid mutation");
    void'($value$plusargs("SVA_OFF=%d",sva_off));void'($value$plusargs("SVA_FAULT=%d",sva_fault));
    $dumpfile(wave);$dumpvars(0,top);catcher=new;uvm_report_cb::add(null,catcher);
    uvm_config_db#(virtual apb_if)::set(null,"uvm_test_top","bus",bus);
    uvm_config_db#(virtual stream_if)::set(null,"uvm_test_top","stream",stream);
    run_test("coord_test");
  end
  initial begin #10000000;$fatal(1,"coordination watchdog");end
endmodule
