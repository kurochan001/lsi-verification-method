`timescale 1ns/1ps
`include "uvm_macros.svh"
package migration_pkg;
  import uvm_pkg::*;
  import uvm_apb_pkg::*;

  class migration_cfg extends uvm_object;
    `uvm_object_utils(migration_cfg)
    virtual apb_if vif;
    virtual replay_control_if control;
    uvm_active_passive_enum mode = UVM_PASSIVE;
    int wait_cycles, planned;
    bit scoreboard_enabled = 1;
    function new(string name="migration_cfg"); super.new(name); endfunction
  endclass

  class cycle_item extends apb_item;
    `uvm_object_utils(cycle_item)
    int cycle;
    bit sel, enable, ready;
    bit [31:0] config_before;
    bit [3:0] pending_before;
    function new(string name="cycle_item"); super.new(name); endfunction
  endclass

  class migration_monitor extends uvm_monitor;
    `uvm_component_utils(migration_monitor)
    migration_cfg cfg;
    uvm_analysis_port #(apb_item) observed;
    int samples;
    function new(string name, uvm_component parent);
      super.new(name,parent); observed=new("observed",this);
    endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(cfg==null || cfg.vif==null || cfg.control==null)
        `uvm_fatal("MIG_CFG","monitor configuration is incomplete")
    endfunction
    virtual function void publish(cycle_item t);
      samples++;
      observed.write(t);
      $display("MIG_TRACE %0d %h %h %h %h %h %h %h %h %h %h %h %h %h %h",
        t.cycle,!t.reset,t.sel,t.enable,t.write,t.addr,t.data,t.events,
        t.ready,t.error,t.rdata,t.config_before,t.pending_before,
        t.actual_config,t.actual_pending);
    endfunction
    task run_phase(uvm_phase phase);
      forever begin
        cycle_item t;
        @(posedge cfg.vif.clk);
        if(!cfg.control.sample_valid) continue;
        t=cycle_item::type_id::create("sample");
        t.cycle=cfg.control.cycle; t.reset=!cfg.vif.rst_n;
        t.sel=cfg.vif.psel; t.enable=cfg.vif.penable; t.ready=cfg.vif.pready;
        t.done=t.sel && t.enable && t.ready;
        t.write=cfg.vif.pwrite; t.addr=cfg.vif.paddr; t.data=cfg.vif.pwdata;
        t.events=cfg.vif.events; t.error=cfg.vif.pslverr; t.rdata=cfg.vif.prdata;
        t.config_before=cfg.vif.config_value; t.pending_before=cfg.vif.pending;
        #1;
        t.actual_config=cfg.vif.config_value; t.actual_pending=cfg.vif.pending;
        publish(t);
      end
    endtask
  endclass

  // A checker-input fault, separate from the three RTL mutations.
  class corrupt_monitor extends migration_monitor;
    `uvm_component_utils(corrupt_monitor)
    bit injected;
    function new(string name,uvm_component parent); super.new(name,parent); endfunction
    virtual function void publish(cycle_item t);
      if(!injected && !t.reset && t.done && t.write && t.addr==0) begin
        t.actual_config^=1; injected=1;
      end
      super.publish(t);
    endfunction
  endclass

  class migration_agent extends uvm_agent;
    `uvm_component_utils(migration_agent)
    migration_cfg cfg;
    migration_monitor monitor;
    apb_driver driver;
    uvm_sequencer #(apb_item) sequencer;
    function new(string name,uvm_component parent); super.new(name,parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(!uvm_config_db#(migration_cfg)::get(this,"","cfg",cfg) || cfg==null)
        `uvm_fatal("MIG_CFG","agent configuration is missing")
      is_active=cfg.mode;
      monitor=migration_monitor::type_id::create("monitor",this); monitor.cfg=cfg;
      if(get_is_active()==UVM_ACTIVE) begin
        sequencer=new("sequencer",this);
        uvm_config_db#(virtual apb_if)::set(this,"driver","vif",cfg.vif);
        driver=apb_driver::type_id::create("driver",this);
      end
    endfunction
    function void connect_phase(uvm_phase phase);
      super.connect_phase(phase);
      if(get_is_active()==UVM_ACTIVE)
        driver.seq_item_port.connect(sequencer.seq_item_export);
    endfunction
  endclass

  class migration_scoreboard extends apb_scoreboard;
    `uvm_component_utils(migration_scoreboard)
    migration_cfg plan;
    // The original scoreboard's write() is not virtual. Bind an imp to this type.
    uvm_analysis_imp #(apb_item,migration_scoreboard) migrated;
    int elapsed;
    bit previous_active, must_hold, previous_done, old_write;
    bit [7:0] old_address;
    bit [31:0] old_data;
    function new(string name,uvm_component parent);
      super.new(name,parent); migrated=new("migrated",this);
    endfunction
    function void fail(string id);
      $display("CHECK_FAIL %s",id);
      `uvm_fatal(id,"protocol observation differs from the migration contract")
    endfunction
    virtual function void write(apb_item sample);
      cycle_item t;
      bit ready_expected, invalid;
      string address_class;
      if(!$cast(t,sample)) begin fail("MIG_ITEM_TYPE"); return; end
      if(t.reset) begin
        if(t.ready || t.error) fail("MIG_RESET_RESPONSE");
      end else begin
        if(must_hold && (!t.sel || !t.enable || t.addr!=old_address ||
           t.write!=old_write || (t.write && t.data!=old_data))) fail("MIG_MASTER_STABILITY");
        if(t.sel && t.enable && !previous_active) fail("MIG_MASTER_SETUP");
        if(previous_done && t.sel && t.enable) fail("MIG_MASTER_BACK_TO_BACK");
        ready_expected=t.sel && t.enable && elapsed>=plan.wait_cycles;
        invalid=!(t.addr inside {0,4,8}) || (t.write && t.addr==4);
        if(t.ready!=ready_expected) fail("MIG_READY");
        if(t.error!=(ready_expected && invalid)) fail("MIG_RESPONSE");
      end
      // Keep the existing UVM reference model and state/read comparisons.
      super.write(sample);
      // Preserve the *legacy* goal IDs, separately from the base class's COVER log.
      if(t.reset) begin
        if(t.sel && t.enable) $display("MIG_COVER reset/access");
        else if(t.sel) $display("MIG_COVER reset/setup");
        else $display("MIG_COVER reset/idle");
        elapsed=0;
      end else begin
        if(previous_done && t.sel && !t.enable) $display("MIG_COVER bus/back-to-back");
        if(t.sel && t.enable && !t.done) $display("MIG_COVER bus/wait");
        if(t.done) begin
          case(t.addr)
            0:address_class="config"; 4:address_class="id"; 8:address_class="pending";
            1:address_class="unaligned"; default:address_class="unmapped";
          endcase
          if(t.write) $display("MIG_COVER cross/%s/write",address_class);
          else $display("MIG_COVER cross/%s/read",address_class);
          if(t.write && t.addr==0) begin
            if(t.data==0) $display("MIG_COVER data/zero");
            if(t.data=='1) $display("MIG_COVER data/ones");
            if(t.data==32'h55555555) $display("MIG_COVER data/alternating");
          end
          if(t.write && t.addr==8) begin
            if(|(t.events & t.data[3:0])) $display("MIG_COVER w1c/event-wins");
            if(t.data[3:0]==0) $display("MIG_COVER w1c/zero");
            if(t.data[3:0]==15 && t.events==0) $display("MIG_COVER w1c/clear-all");
          end
        end
        if(t.sel && !t.enable) elapsed=0;
        else if(t.sel && t.enable) elapsed++;
      end
      previous_active=!t.reset && t.sel;
      must_hold=!t.reset && t.sel && (!t.enable || !t.done);
      previous_done=!t.reset && t.done;
      old_address=t.addr; old_write=t.write; old_data=t.data;
    endfunction
  endclass

  class migration_env extends uvm_env;
    `uvm_component_utils(migration_env)
    migration_cfg cfg;
    migration_agent agent;
    migration_scoreboard scoreboard;
    function new(string name,uvm_component parent); super.new(name,parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(!uvm_config_db#(migration_cfg)::get(this,"","cfg",cfg))
        `uvm_fatal("MIG_CFG","environment configuration is missing")
      uvm_config_db#(migration_cfg)::set(this,"agent","cfg",cfg);
      agent=migration_agent::type_id::create("agent",this);
      scoreboard=migration_scoreboard::type_id::create("scoreboard",this); scoreboard.plan=cfg;
    endfunction
    function void connect_phase(uvm_phase phase);
      super.connect_phase(phase);
      if(cfg.scoreboard_enabled) agent.monitor.observed.connect(scoreboard.migrated);
    endfunction
  endclass

  class migration_test extends uvm_test;
    `uvm_component_utils(migration_test)
    migration_cfg cfg;
    migration_env env;
    function new(string name,uvm_component parent); super.new(name,parent); endfunction
    function void build_phase(uvm_phase phase);
      int active, monitor_fault, checker_off;
      super.build_phase(phase); cfg=migration_cfg::type_id::create("cfg");
      if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",cfg.vif) ||
         !uvm_config_db#(virtual replay_control_if)::get(this,"","control",cfg.control))
        `uvm_fatal("MIG_CFG","test interfaces are missing")
      if(!$value$plusargs("WAIT_CYCLES=%d",cfg.wait_cycles) ||
         !$value$plusargs("CHECKS=%d",cfg.planned)) `uvm_fatal("MIG_CFG","plan is missing")
      void'($value$plusargs("ACTIVE=%d",active));
      void'($value$plusargs("MONITOR_FAULT=%d",monitor_fault));
      void'($value$plusargs("CHECKER_OFF=%d",checker_off));
      cfg.mode=active ? UVM_ACTIVE:UVM_PASSIVE;
      cfg.scoreboard_enabled=!checker_off;
      if(monitor_fault) migration_monitor::type_id::set_type_override(corrupt_monitor::get_type());
      uvm_config_db#(migration_cfg)::set(this,"env","cfg",cfg);
      env=migration_env::type_id::create("env",this);
    endfunction
    function void end_of_elaboration_phase(uvm_phase phase);
      super.end_of_elaboration_phase(phase);
      if(env.agent.driver!=null || env.agent.sequencer!=null) begin
        $display("CHECK_FAIL MIG_OWNERSHIP");
        `uvm_fatal("MIG_OWNERSHIP","legacy replay requires a passive agent")
      end
      $display("MIG_OWNERSHIP passive driver=0 sequencer=0 legacy=1");
    endfunction
    task run_phase(uvm_phase phase);
      uvm_event done_event=uvm_event_pool::get_global("legacy_replay_complete");
      phase.raise_objection(this);
      cfg.control.start_replay=1;
      done_event.wait_on();
      #1;
      phase.drop_objection(this);
    endtask
    function void check_phase(uvm_phase phase);
      super.check_phase(phase);
      if(env.agent.monitor.samples!=cfg.planned || env.scoreboard.checks!=cfg.planned || cfg.planned<=0) begin
        $display("CHECK_FAIL MIG_COMPARISONS");
        `uvm_fatal("MIG_COMPARISONS","missing observations or comparisons")
      end
    endfunction
    function void report_phase(uvm_phase phase);
      uvm_report_server server=uvm_report_server::get_server();
      super.report_phase(phase);
      if(server.get_severity_count(UVM_ERROR)!=0 || server.get_severity_count(UVM_FATAL)!=0)
        $fatal(1,"UVM report contains errors");
      $display("MIG_COMPLETE samples=%0d comparisons=%0d",env.agent.monitor.samples,env.scoreboard.checks);
      $display("RESULT PASS checks=%0d",env.scoreboard.checks);
    endfunction
  endclass
endpackage
