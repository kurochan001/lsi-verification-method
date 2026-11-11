`timescale 1ns/1ps
`include "uvm_macros.svh"
module top;
  import uvm_pkg::*;import uvm_apb_pkg::*;import hierarchy_pkg::*;
  bit clk=0;always #5 clk=!clk;
  apb_if bus(clk),bank0(clk),bank1(clk);
  int layout,mutation,sva_fault,sva_off;bit [7:0] tick;
  wire select0=bus.paddr[7:4]==(layout ? 4:0);
  wire select1=bus.paddr[7:4]==(layout ? 0:4);
  wire s0=select0 || (mutation==3 && select1);
  wire s1=select1 && mutation!=3;
  // The interface variables have initial values, so they are driven from a process: a continuous
  // assignment to a variable that also has an initializer is not legal.
  always_comb begin
    bank0.rst_n=bus.rst_n;bank1.rst_n=bus.rst_n;
    bank0.psel=bus.psel && s0;bank1.psel=bus.psel && s1;
    bank0.penable=bus.penable;bank1.penable=bus.penable;
    bank0.pwrite=bus.pwrite;bank1.pwrite=bus.pwrite;
    bank0.paddr={4'b0,bus.paddr[3:0]};bank1.paddr={4'b0,bus.paddr[3:0]};
    bank0.pwdata=bus.pwdata;bank1.pwdata=bus.pwdata;
  end
  wire [31:0] rdata[3],cfg[3];wire [3:0] pending[3];wire ready[3],error_response[3];
  apb_regs #(.WAIT_CYCLES(1)) ip0(clk,bank0.rst_n,bank0.psel,bank0.penable,bank0.pwrite,bank0.paddr,bank0.pwdata,bank0.events,bank0.pready,bank0.pslverr,bank0.prdata,bank0.config_value,bank0.pending);
  for(genvar m=0;m<3;m++)begin: variants
    apb_regs #(.WAIT_CYCLES(2),.MUTATION(m)) ip1(clk,bank1.rst_n,bank1.psel,bank1.penable,bank1.pwrite,bank1.paddr,bank1.pwdata,bank1.events,ready[m],error_response[m],rdata[m],cfg[m],pending[m]);
  end
  wire [1:0] which=mutation inside {1,2} ? mutation:0;
  assign bank1.pready=ready[which];assign bank1.pslverr=error_response[which];
  assign bank1.prdata=rdata[which];assign bank1.config_value=cfg[which];assign bank1.pending=pending[which];
  assign bus.pready=select0 ? bank0.pready:select1 ? (mutation==3 ? bank0.pready:bank1.pready):bus.rst_n && bus.psel && bus.penable;
  assign bus.pslverr=select0 ? bank0.pslverr:select1 ? (mutation==3 ? bank0.pslverr:bank1.pslverr):bus.psel && bus.penable;
  assign bus.prdata=select0 ? bank0.prdata:select1 ? (mutation==3 ? bank0.prdata:bank1.prdata):0;
  wire [7:0] observed_addr=bus.paddr ^ ((sva_fault && bus.psel && bus.penable) ? tick:0);
  ap_stability:assert property(@(posedge clk) disable iff(!bus.rst_n || sva_off)
    (bus.psel && bus.penable && !bus.pready) |=> (bus.psel && bus.penable && $stable({observed_addr,bus.pwrite,bus.pwdata})))
    else begin $display("CHECK_FAIL HIER_STABILITY");$fatal(1,"APB controls changed during wait");end
  cp_leaf0:cover property(@(posedge clk) !sva_off && bank0.psel && bank0.penable && bank0.pready)$display("HIER_COVER cp_leaf0");
  cp_leaf1:cover property(@(posedge clk) !sva_off && bank1.psel && bank1.penable && bank1.pready)$display("HIER_COVER cp_leaf1");
  cp_reset:cover property(@(posedge clk) !sva_off && !bus.rst_n)$display("HIER_COVER cp_reset");
  always @(posedge clk)tick<=tick+1;
  initial begin
    string wave;fatal_to_exit catcher;
    bus.rst_n=0;bus.psel=0;bus.penable=0;bus.pwrite=0;bus.paddr=0;bus.pwdata=0;bank0.events=0;bank1.events=0;
    void'($value$plusargs("LAYOUT=%d",layout));void'($value$plusargs("MUTATION=%d",mutation));
    void'($value$plusargs("SVA_FAULT=%d",sva_fault));void'($value$plusargs("SVA_OFF=%d",sva_off));
    if(layout<0 || layout>1 || mutation<0 || mutation>3 || !$value$plusargs("WAVE=%s",wave))$fatal(1,"invalid run arguments");
    $dumpfile(wave);$dumpvars(0,top);catcher=new;uvm_report_cb::add(null,catcher);
    uvm_config_db#(virtual apb_if)::set(null,"uvm_test_top.env","bus",bus);
    uvm_config_db#(virtual apb_if)::set(null,"uvm_test_top.env","bank0",bank0);
    uvm_config_db#(virtual apb_if)::set(null,"uvm_test_top.env","bank1",bank1);
    run_test("hierarchy_test");
  end
  initial begin #10000000;$fatal(1,"hierarchy watchdog");end
endmodule
