`timescale 1ps/1ps
`include "uvm_macros.svh"
module top;
 import uvm_pkg::*;import oo_pkg::*;
 bit clk=0;always #5000 clk=!clk;
 oo_if bus(clk);int mutation,sva_off;
 wire [4:0]s_ready,m_valid;wire [1:0]m_id[5];wire [15:0]m_token[5];wire [7:0]m_data[5];
 for(genvar m=0;m<5;m++)begin: variants
  tagged_reorder #(.MUTATION(m)) dut(clk,bus.rst_n,bus.release_enable,bus.s_valid,bus.s_id,bus.s_token,bus.s_data,s_ready[m],m_valid[m],bus.m_ready,m_id[m],m_token[m],m_data[m]);
 end
 assign bus.s_ready=s_ready[mutation];assign bus.m_valid=m_valid[mutation];assign bus.m_id=m_id[mutation];assign bus.m_token=m_token[mutation];assign bus.m_data=m_data[mutation];
 bit [3:0]queued,seen;int age[4],serial;bit reset_seen,older;
 always @*begin older=0;for(int i=0;i<4;i++)if(queued[i] && age[i]<age[bus.m_id])older=1;end
 always @(posedge clk)begin
  if(!bus.rst_n)begin if(queued!=0)reset_seen<=1;queued<=0;end
  else begin
   if(bus.s_valid && bus.s_ready)begin queued[bus.s_id]<=1;seen[bus.s_id]<=1;age[bus.s_id]<=serial;serial<=serial+1;end
   if(bus.m_valid && bus.m_ready)queued[bus.m_id]<=0;
  end
 end
 ap_hold:assert property(@(posedge clk) disable iff(!bus.rst_n || sva_off!=0)
  (bus.m_valid && !bus.m_ready)|=>(bus.m_valid && $stable({bus.m_id,bus.m_token,bus.m_data})))
  else begin $display("CHECK_FAIL OO_HOLD");$fatal(1,"response changed while stalled");end
 cp_accept:cover property(@(posedge clk) sva_off==0 && bus.rst_n && bus.s_valid && bus.s_ready)$display("OO_COVER cp_accept");
 cp_response:cover property(@(posedge clk) sva_off==0 && bus.rst_n && bus.m_valid && bus.m_ready)$display("OO_COVER cp_response");
 cp_stall:cover property(@(posedge clk) sva_off==0 && bus.rst_n && bus.m_valid && !bus.m_ready)$display("OO_COVER cp_stall");
 cp_full:cover property(@(posedge clk) sva_off==0 && bus.rst_n && &queued)$display("OO_COVER cp_full");
 cp_reuse:cover property(@(posedge clk) sva_off==0 && bus.rst_n && bus.s_valid && bus.s_ready && seen[bus.s_id])$display("OO_COVER cp_reuse");
 cp_ooo:cover property(@(posedge clk) sva_off==0 && bus.rst_n && bus.m_valid && bus.m_ready && older)$display("OO_COVER cp_ooo");
 cp_reset:cover property(@(posedge clk) sva_off==0 && !bus.rst_n && queued!=0)$display("OO_COVER cp_reset");
 cp_recovery:cover property(@(posedge clk) sva_off==0 && bus.rst_n && bus.m_valid && bus.m_ready && reset_seen)$display("OO_COVER cp_recovery");
 initial begin
  string wave;fatal_to_exit catcher;
  void'($value$plusargs("MUTATION=%d",mutation));void'($value$plusargs("SVA_OFF=%d",sva_off));
  if(mutation<0 || mutation>4 || !$value$plusargs("WAVE=%s",wave))$fatal(1,"invalid arguments");
  $dumpfile(wave);$dumpvars(0,top);catcher=new;uvm_report_cb::add(null,catcher);
  uvm_config_db#(virtual oo_if)::set(null,"uvm_test_top.env","vif",bus);run_test("oo_test");
 end
 initial begin #100000000;$fatal(1,"outstanding watchdog");end
endmodule
