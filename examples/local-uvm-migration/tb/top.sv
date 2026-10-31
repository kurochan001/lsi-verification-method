`timescale 1ns/1ps
`include "uvm_macros.svh"
module top;
  import uvm_pkg::*;
  import uvm_apb_pkg::*;
  import migration_pkg::*;
  bit clk=0;
  apb_if bus(clk);
  replay_control_if control();
  int wait_cycles, wait_index, mutation, sva_fault, sva_off, planned;
  wire [31:0] data_values[3][4], config_values[3][4];
  wire [3:0] pending_values[3][4];
  wire ready_values[3][4], error_values[3][4];
  for(genvar w=0;w<3;w++) begin: configurations
    for(genvar m=0;m<4;m++) begin: mutations
      apb_regs #(.WAIT_CYCLES(w==2 ? 3:w),.MUTATION(m)) dut(
        clk,bus.rst_n,bus.psel,bus.penable,bus.pwrite,bus.paddr,bus.pwdata,bus.events,
        ready_values[w][m],error_values[w][m],data_values[w][m],config_values[w][m],pending_values[w][m]);
    end
  end
  assign bus.pready=ready_values[wait_index][mutation];
  assign bus.pslverr=error_values[wait_index][mutation];
  assign bus.prdata=data_values[wait_index][mutation];
  assign bus.config_value=config_values[wait_index][mutation];
  assign bus.pending=pending_values[wait_index][mutation];
  wire [31:0] checked_config=bus.config_value ^ (sva_fault ? 32'b1:32'b0);
  bit history_valid=0;
  always @(posedge clk) history_valid<=1;
  // The reset property is not disabled by reset itself. Its result is sampled next edge.
  ap_sync_reset: assert property (@(posedge clk) disable iff(!control.sva_enabled)
    (control.sample_valid && !bus.rst_n) |=> checked_config==0)
    else begin
      $display("CHECK_FAIL MIG_SYNC_RESET");
      `uvm_error("MIG_SYNC_RESET","synchronous reset result differs")
    end
  cp_reset_seen: cover property (@(posedge clk)
    control.sva_enabled && control.sample_valid && !bus.rst_n)
    $display("MIG_SVA_COVER cp_reset_seen");
  cp_reset_done: cover property (@(posedge clk)
    control.sva_enabled && history_valid &&
    $past(control.sva_enabled && control.sample_valid && !bus.rst_n) && checked_config==0)
    $display("MIG_SVA_COVER cp_reset_done");
  always #5 clk=!clk;
  string vectors,wave;
  fatal_to_exit catcher;
  initial begin
    if(!$value$plusargs("WAIT_CYCLES=%d",wait_cycles) ||
       !$value$plusargs("MUTATION=%d",mutation) ||
       !$value$plusargs("CHECKS=%d",planned) ||
       !$value$plusargs("VECTORS=%s",vectors) ||
       !$value$plusargs("WAVE=%s",wave)) $fatal(1,"missing replay arguments");
    if(!(wait_cycles inside {0,1,3}) || mutation<0 || mutation>3) $fatal(1,"invalid configuration");
    wait_index=wait_cycles==3 ? 2:wait_cycles;
    void'($value$plusargs("SVA_FAULT=%d",sva_fault));
    void'($value$plusargs("SVA_OFF=%d",sva_off));
    control.sva_enabled=!sva_off;
    $dumpfile(wave);$dumpvars(0,top);
    catcher=new;uvm_report_cb::add(null,catcher);
    uvm_config_db#(virtual apb_if)::set(null,"uvm_test_top","vif",bus);
    uvm_config_db#(virtual replay_control_if)::set(null,"uvm_test_top","control",control);
    run_test("migration_test");
  end
  initial begin: legacy_reader
    int fd,fields,r,s,e,w,a,event_bits,seen;
    bit [31:0] data;
    uvm_event done_event=uvm_event_pool::get_global("legacy_replay_complete");
    wait(control.start_replay);
    fd=$fopen(vectors,"r");if(!fd) $fatal(1,"cannot read replay vectors");
    while(!$feof(fd)) begin
      fields=$fscanf(fd,"%d %d %d %d %h %h %h\n",r,s,e,w,a,data,event_bits);
      if(fields!=7) $fatal(1,"bad vector format");
      @(negedge clk);
      bus.rst_n=r;bus.psel=s;bus.penable=e;bus.pwrite=w;
      bus.paddr=a;bus.pwdata=data;bus.events=event_bits;
      control.sample_valid=1;control.cycle=seen+1;
      @(posedge clk);#2;seen++;
    end
    $fclose(fd);
    if(seen!=planned) $fatal(1,"replay count differs from plan");
    control.sample_valid=0;
    done_event.trigger();
  end
  initial begin #1000000;$fatal(1,"replay watchdog");end
endmodule
