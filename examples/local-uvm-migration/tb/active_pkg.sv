`timescale 1ns/1ps
`include "uvm_macros.svh"
package active_migration_pkg;
  import uvm_pkg::*;
  import uvm_apb_pkg::*;
  import migration_pkg::*;

  // A cycle item preserves reset/aborted accesses as well as completed transfers.
  class replay_sequence extends uvm_sequence #(apb_item);
    `uvm_object_utils(replay_sequence)
    function new(string name="replay_sequence"); super.new(name); endfunction
    task body();
      string vectors;
      int fd,fields,r,s,e,w,a,event_bits,seen;
      bit [31:0] data;
      if(!$value$plusargs("VECTORS=%s",vectors)) `uvm_fatal("MIG_VECTOR","missing vectors")
      fd=$fopen(vectors,"r"); if(!fd) `uvm_fatal("MIG_VECTOR","cannot open vectors")
      while(!$feof(fd)) begin
        cycle_item t;
        fields=$fscanf(fd,"%d %d %d %d %h %h %h\n",r,s,e,w,a,data,event_bits);
        if(fields!=7) `uvm_fatal("MIG_VECTOR","bad vector format")
        t=cycle_item::type_id::create("cycle"); start_item(t);
        t.cycle=seen+1; t.reset=!r; t.sel=s; t.enable=e; t.write=w;
        t.addr=a; t.data=data; t.events=event_bits;
        finish_item(t); seen++;
      end
      $fclose(fd);
    endtask
  endclass

  class replay_driver extends apb_driver;
    `uvm_component_utils(replay_driver)
    virtual replay_control_if control;
    function new(string name,uvm_component parent); super.new(name,parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(!uvm_config_db#(virtual replay_control_if)::get(this,"","control",control))
        `uvm_fatal("MIG_CFG","active driver control is missing")
    endfunction
    task run_phase(uvm_phase phase);
      forever begin
        apb_item item;
        cycle_item cycle;
        seq_item_port.get_next_item(item);
        if($cast(cycle,item)) begin
          @(negedge vif.clk);
          vif.rst_n=!cycle.reset; vif.psel=cycle.sel; vif.penable=cycle.enable;
          vif.pwrite=cycle.write; vif.paddr=cycle.addr; vif.pwdata=cycle.data; vif.events=cycle.events;
          control.sample_valid=1; control.cycle=cycle.cycle;
          @(posedge vif.clk); #2;
        end else begin
          // M4: the same sequencer/adapter can issue RAL frontdoor accesses.
          @(negedge vif.clk); vif.psel=1; vif.penable=0;
          vif.pwrite=item.write; vif.paddr=item.addr; vif.pwdata=item.data; vif.events=0;
          @(negedge vif.clk); vif.penable=1;
          do begin @(posedge vif.clk); end while(!vif.pready);
          item.rdata=vif.prdata; item.error=vif.pslverr;
          @(negedge vif.clk); vif.psel=0; vif.penable=0;
        end
        seq_item_port.item_done();
      end
    endtask
  endclass

  class active_migration_test extends migration_test;
    `uvm_component_utils(active_migration_test)
    int ral_checks;
    function new(string name,uvm_component parent); super.new(name,parent); endfunction
    function void build_phase(uvm_phase phase);
      apb_driver::type_id::set_type_override(replay_driver::get_type());
      super.build_phase(phase);
      uvm_config_db#(virtual replay_control_if)::set(this,"env.agent.driver","control",cfg.control);
    endfunction
    function void end_of_elaboration_phase(uvm_phase phase);
      if(env.agent.driver==null || env.agent.sequencer==null || cfg.mode!=UVM_ACTIVE || cfg.control.start_replay) begin
        $display("CHECK_FAIL MIG_OWNERSHIP");
        `uvm_fatal("MIG_OWNERSHIP","active replay requires one UVM driver and no legacy replay")
      end
      $display("MIG_OWNERSHIP active driver=1 sequencer=1 legacy=0");
    endfunction
    task run_phase(uvm_phase phase);
      replay_sequence replay;
      apb_block model;
      apb_adapter adapter;
      uvm_status_e status;
      uvm_reg_data_t value;
      int skip_ral,bad_expected;
      phase.raise_objection(this);
      replay=replay_sequence::type_id::create("saved_cycles");
      replay.start(env.agent.sequencer);
      cfg.control.sample_valid=0;
      void'($value$plusargs("RAL_OFF=%d",skip_ral));
      void'($value$plusargs("RAL_BAD_EXPECTED=%d",bad_expected));
      if(!skip_ral) begin
        model=apb_block::type_id::create("additional_ral");model.build();
        adapter=apb_adapter::type_id::create("adapter");
        model.default_map.set_sequencer(env.agent.sequencer,adapter);model.default_map.set_auto_predict(1);
        model.cfg.write(status,32'h5a,UVM_FRONTDOOR);
        if(status!=UVM_IS_OK) `uvm_fatal("MIG_RAL","write failed")
        ral_checks++;
        model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);
        if(status!=UVM_IS_OK) `uvm_fatal("MIG_RAL","mirror failed")
        model.cfg.read(status,value,UVM_FRONTDOOR);
        if(status!=UVM_IS_OK || value!=(bad_expected ? 32'h5b:32'h5a)) begin
          $display("CHECK_FAIL MIG_RAL_READBACK");
          `uvm_fatal("MIG_RAL_READBACK","readback differs from the independent expected value")
        end
        ral_checks++;
        model.idreg.read(status,value,UVM_FRONTDOOR);
        if(status!=UVM_IS_OK || value!=32'h41504233) `uvm_fatal("MIG_RAL","ID differs")
        ral_checks++;
        $display("MIG_RAL_COMPLETE checks=%0d",ral_checks);
      end
      #1;phase.drop_objection(this);
    endtask
    function void check_phase(uvm_phase phase);
      super.check_phase(phase);
      if(ral_checks!=3) begin
        $display("CHECK_FAIL MIG_RAL_COMPLETION");
        `uvm_fatal("MIG_RAL_COMPLETION","the additional RAL checks did not complete")
      end
    endfunction
  endclass
endpackage
