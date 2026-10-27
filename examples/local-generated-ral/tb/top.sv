`timescale 1ns/1ps
module top;
 import uvm_pkg::*;import uvm_apb_pkg::*;import front_pkg::*;
 bit clk=0;always #5 clk=~clk;apb_if bus(clk);integer mutation=0,wait_index=0,wait_cycles=0;
 wire[31:0]rdata[0:1][0:3],cfg[0:1][0:3];wire[3:0]pend[0:1][0:3];wire ready[0:1][0:3],error_response[0:1][0:3];
 for(genvar w=0;w<2;w++)begin:wait_config
 for(genvar m=0;m<4;m++)begin:mutant
 rdl_regs #(.MUTATION(m),.WAIT_CYCLES(w*2))dut(.clk(clk),.rst_n(bus.rst_n),.psel(bus.psel),.penable(bus.penable),.pwrite(bus.pwrite),.paddr(bus.paddr),.pwdata(bus.pwdata),.events(bus.events),.pready(ready[w][m]),.pslverr(error_response[w][m]),.prdata(rdata[w][m]));
 assign cfg[w][m]={24'b0,dut.cfg};assign pend[w][m]=dut.pending;
 end end
 assign bus.pready=ready[wait_index][mutation];assign bus.pslverr=error_response[wait_index][mutation];assign bus.prdata=rdata[wait_index][mutation];assign bus.config_value=cfg[wait_index][mutation];assign bus.pending=pend[wait_index][mutation];
 string wave;fatal_to_exit catcher;
 initial begin
 void'($value$plusargs("MUTATION=%d",mutation));void'($value$plusargs("WAIT_CYCLES=%d",wait_cycles));if(mutation<0 || mutation>3 || !(wait_cycles inside {0,2}))$fatal(1,"invalid configuration");wait_index=wait_cycles/2;
 if(!$value$plusargs("WAVE=%s",wave))$fatal(1,"wave required");$dumpfile(wave);$dumpvars(0,top);catcher=new;uvm_report_cb::add(null,catcher);uvm_config_db#(virtual apb_if)::set(null,"*","vif",bus);run_test("front_test");end
 initial begin #1000000;$fatal(1,"watchdog");end
endmodule
