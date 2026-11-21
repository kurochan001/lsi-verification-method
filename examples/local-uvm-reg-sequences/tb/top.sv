`timescale 1ns/1ps
module top;
 import uvm_pkg::*;import reg_seq_pkg::*;
 bit clk=0;always #5 clk=~clk;regbus_if bus(clk);
 integer mutation=0;
 wire [31:0] rdata[0:9];wire ready[0:9],error_response[0:9];
 wire [7:0] ctrl_value[0:9];wire [31:0] scratch_value[0:9];
 for(genvar m=0;m<10;m++)begin:mutant
  reg_bank #(.MUTATION(m)) dut(.clk(clk),.rst_n(bus.rst_n),.psel(bus.psel),.penable(bus.penable),.pwrite(bus.pwrite),.paddr(bus.paddr),.pwdata(bus.pwdata),.events(bus.events),.pready(ready[m]),.pslverr(error_response[m]),.prdata(rdata[m]));
  assign ctrl_value[m]=dut.ctrl;assign scratch_value[m]=dut.scratch;
  // Deposit for the user-defined backdoor: hold the value over the request, then release.
  always @(posedge bus.poke)begin
   if(bus.poke_target)begin force dut.scratch=bus.poke_value;@(negedge bus.poke);release dut.scratch;end
   else begin force dut.ctrl=bus.poke_value[7:0];@(negedge bus.poke);release dut.ctrl;end
  end
 end
 assign bus.pready=ready[mutation];assign bus.pslverr=error_response[mutation];assign bus.prdata=rdata[mutation];
 assign bus.peek_ctrl=ctrl_value[mutation];assign bus.peek_scratch=scratch_value[mutation];
 string wave;stage_catcher catcher;
 initial begin
  void'($value$plusargs("MUTATION=%d",mutation));
  if(mutation<0 || mutation>9)$fatal(1,"invalid configuration");
  if(!$value$plusargs("WAVE=%s",wave))$fatal(1,"wave required");$dumpfile(wave);$dumpvars(0,top);
  catcher=new;uvm_report_cb::add(null,catcher);
  uvm_config_db#(virtual regbus_if)::set(null,"*","vif",bus);run_test("bank_test");
 end
 initial begin #2000000;$display("CHECK_FAIL REG_WATCHDOG");$fatal(1,"testbench watchdog");end
endmodule
