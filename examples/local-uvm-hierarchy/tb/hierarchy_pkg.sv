`timescale 1ns/1ps
`include "uvm_macros.svh"
package hierarchy_pkg;
  import uvm_pkg::*;
  import uvm_apb_pkg::*;

  class leaf_config extends uvm_object;
    `uvm_object_utils(leaf_config)
    virtual apb_if vif;
    apb_block model;
    function new(string name="leaf_config");super.new(name);endfunction
  endclass
  // Reuse the original monitor, independent reference model and register block.
  // The leaf environment never creates a driver or sequencer.
  class leaf_env extends uvm_env;
    `uvm_component_utils(leaf_env)
    leaf_config cfg;
    apb_monitor monitor;
    apb_scoreboard scoreboard;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      if(!uvm_config_db#(leaf_config)::get(this,"","cfg",cfg) || cfg==null || cfg.vif==null || cfg.model==null)
        `uvm_fatal("HIER_CFG","incomplete leaf configuration")
      uvm_config_db#(virtual apb_if)::set(this,"monitor","vif",cfg.vif);
      monitor=apb_monitor::type_id::create("monitor",this);
      scoreboard=apb_scoreboard::type_id::create("scoreboard",this);scoreboard.model=cfg.model;
    endfunction
    function void connect_phase(uvm_phase phase);
      int off;void'($value$plusargs("CHECKER_OFF=%d",off));
      if(!(off && get_name()=="leaf1"))monitor.observed.connect(scoreboard.observed);
    endfunction
  endclass
  class soc_block extends uvm_reg_block;
    `uvm_object_utils(soc_block)
    apb_block leaf[2];
    int layout;
    function new(string name="soc_block");super.new(name,UVM_NO_COVERAGE);endfunction
    function void build();
      int bad;void'($value$plusargs("BAD_MAP=%d",bad));
      default_map=create_map("soc_map",0,4,UVM_LITTLE_ENDIAN);
      for(int b=0;b<2;b++)begin
        leaf[b]=apb_block::type_id::create($sformatf("bank%0d",b));leaf[b].configure(this);leaf[b].build();
        default_map.add_submap(leaf[b].default_map,((b^layout)*64) ^ ((bad && b==1) ? 32:0));
      end
      lock_model();
    endfunction
  endclass
  class hierarchy_env extends uvm_env;
    `uvm_component_utils(hierarchy_env)
    virtual apb_if bus,bank0,bank1;
    apb_driver driver;uvm_sequencer#(apb_item) sequencer;
    leaf_env children[2];soc_block model;apb_adapter adapter;
    int layout;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      int unused;super.build_phase(phase);
      if(!uvm_config_db#(virtual apb_if)::get(this,"","bus",bus) ||
         !uvm_config_db#(virtual apb_if)::get(this,"","bank0",bank0) ||
         !uvm_config_db#(virtual apb_if)::get(this,"","bank1",bank1))`uvm_fatal("HIER_CFG","missing physical interfaces")
      void'($value$plusargs("LAYOUT=%d",layout));
      model=soc_block::type_id::create("model");model.layout=layout;model.build();
      adapter=apb_adapter::type_id::create("adapter");sequencer=new("sequencer",this);
      uvm_config_db#(virtual apb_if)::set(this,"driver","vif",bus);driver=apb_driver::type_id::create("driver",this);
      for(int b=0;b<2;b++)begin
        leaf_config c=leaf_config::type_id::create($sformatf("cfg%0d",b));
        if(b==0)c.vif=bank0;else c.vif=bank1;c.model=model.leaf[b];
        uvm_config_db#(leaf_config)::set(this,$sformatf("leaf%0d",b),"cfg",c);
        children[b]=leaf_env::type_id::create($sformatf("leaf%0d",b),this);
      end
    endfunction
    function void connect_phase(uvm_phase phase);
      driver.seq_item_port.connect(sequencer.seq_item_export);
      model.default_map.set_sequencer(sequencer,adapter);model.default_map.set_auto_predict(1);
    endfunction
    function void end_of_elaboration_phase(uvm_phase phase);
      for(int b=0;b<2;b++)if(model.leaf[b].cfg.get_address()!=((b^layout)*64))begin
        $display("CHECK_FAIL HIER_MAP");`uvm_fatal("HIER_MAP","submap differs from the physical address map")
      end
      $display("HIER_OWNERSHIP active_drivers=1 passive_children=2");
    endfunction
  endclass
  class unmapped_sequence extends uvm_sequence#(apb_item);
    `uvm_object_utils(unmapped_sequence)
    function new(string name="unmapped_sequence");super.new(name);endfunction
    task body();
      apb_item t=apb_item::type_id::create("unmapped_check");start_item(t);t.addr='h80;t.write=0;finish_item(t);
      if(!t.error || t.rdata!=0)begin $display("CHECK_FAIL HIER_RESPONSE");`uvm_fatal("HIER_RESPONSE","unmapped access must fail without data") end
    endtask
  endclass
  class soc_sequence extends uvm_sequence#(uvm_sequence_item);
    `uvm_object_utils(soc_sequence)
    hierarchy_env env;int iterations,checks;
    int unsigned state;
    function new(string name="soc_sequence");super.new(name);endfunction
    task good(uvm_status_e status);
      if(status!=UVM_IS_OK)begin $display("CHECK_FAIL HIER_STATUS");`uvm_fatal("HIER_STATUS","frontdoor access failed") end
    endtask
    task expect_read(uvm_reg reg_handle,uvm_reg_data_t expected);
      uvm_status_e status;uvm_reg_data_t value;
      reg_handle.read(status,value,UVM_FRONTDOOR);good(status);
      if(value!==expected)begin $display("CHECK_FAIL HIER_READ");`uvm_fatal("HIER_READ","read differs from the independently retained expectation") end
      checks++;
    endtask
    task reset_both();
      @(negedge env.bus.clk);env.bus.rst_n=0;env.bank0.events=0;env.bank1.events=0;
      repeat(3)@(negedge env.bus.clk);env.model.reset();env.bus.rst_n=1;@(negedge env.bus.clk);
    endtask
    task body();
      uvm_status_e status;uvm_reg_data_t expected[2];unmapped_sequence raw;
      reset_both();
      for(int b=0;b<2;b++)expect_read(env.model.leaf[b].idreg,32'h41504233);
      for(int i=0;i<iterations;i++)begin
        for(int b=0;b<2;b++)begin
          state=state*1664525+1013904223;expected[b]=state;
          env.model.leaf[b].cfg.write(status,expected[b],UVM_FRONTDOOR);good(status);
        end
        for(int b=0;b<2;b++)begin
          env.model.leaf[b].cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);
          expect_read(env.model.leaf[b].cfg,expected[b]);$display("COVER hierarchy/b%0d/readback",b);
        end
      end
      @(negedge env.bus.clk);env.bank0.events=1;env.bank1.events=2;
      for(int b=0;b<2;b++)begin
        env.model.leaf[b].pend.write(status,15,UVM_FRONTDOOR);good(status);
      end
      @(negedge env.bus.clk);env.bank0.events=0;env.bank1.events=0;
      for(int b=0;b<2;b++)begin
        // Hardware events are predicted from the stimulus contract, never DUT state.
        if(!env.model.leaf[b].pend.predict(1<<b))`uvm_fatal("HIER_PREDICT","prediction failed")
        expect_read(env.model.leaf[b].pend,1<<b);
        env.model.leaf[b].pend.write(status,15,UVM_FRONTDOOR);good(status);
        expect_read(env.model.leaf[b].pend,0);$display("COVER hierarchy/b%0d/pending",b);
      end
      reset_both();
      for(int b=0;b<2;b++)begin expect_read(env.model.leaf[b].cfg,0);$display("COVER hierarchy/b%0d/reset",b);end
      raw=unmapped_sequence::type_id::create("unmapped");raw.start(env.sequencer);
      checks++;$display("COVER hierarchy/unmapped");
    endtask
  endclass
  class hierarchy_test extends uvm_test;
    `uvm_component_utils(hierarchy_test)
    hierarchy_env env;soc_sequence scenario;int iterations=4,seed=17;bit finished;
    function new(string name,uvm_component parent);super.new(name,parent);endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);env=hierarchy_env::type_id::create("env",this);
      void'($value$plusargs("ITERATIONS=%d",iterations));void'($value$plusargs("SEED=%d",seed));
    endfunction
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);scenario=soc_sequence::type_id::create("scenario");
      scenario.env=env;scenario.iterations=iterations;scenario.state=seed;scenario.start(null);
      repeat(2)@(negedge env.bus.clk);finished=1;phase.drop_objection(this);
    endtask
    function void check_phase(uvm_phase phase);
      if(!finished || scenario.checks!=2*iterations+9 ||
         env.children[0].scoreboard.transactions!=3*iterations+6 || env.children[1].scoreboard.transactions!=3*iterations+6)begin
        $display("CHECK_FAIL HIER_COUNTS");`uvm_fatal("HIER_COUNTS","missing comparisons, observations or completion")
      end
    endfunction
    function void report_phase(uvm_phase phase);
      uvm_report_server s=uvm_report_server::get_server();
      if(s.get_severity_count(UVM_ERROR)!=0 || s.get_severity_count(UVM_FATAL)!=0)begin
        $display("CHECK_FAIL HIER_SUMMARY");$fatal(1,"native UVM contains errors");
      end
      $display("HIER_COMPLETE bank0=%0d bank1=%0d",env.children[0].scoreboard.transactions,env.children[1].scoreboard.transactions);
      $display("RESULT PASS checks=%0d",scenario.checks);
    endfunction
  endclass
endpackage
