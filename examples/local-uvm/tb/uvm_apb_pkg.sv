`include "uvm_macros.svh"
package uvm_apb_pkg;
 import uvm_pkg::*;
 // Map UVM_FATAL to a nonzero process exit; the default UVM $finish can exit 0.
 class fatal_to_exit extends uvm_report_catcher;
  function new(string n="fatal_to_exit");super.new(n);endfunction
  virtual function action_e catch();
   if(get_severity()==UVM_FATAL)$fatal(1,"UVM_FATAL %s: %s",get_id(),get_message());
   return THROW;
  endfunction
 endclass
 class apb_item extends uvm_sequence_item;
  `uvm_object_utils(apb_item)
  bit write;bit [7:0] addr;bit [31:0] data,rdata;bit error,done,reset;
  bit [3:0] events;bit [31:0] actual_config;bit [3:0] actual_pending;
  function new(string name="apb_item");super.new(name);endfunction
 endclass
 class apb_driver extends uvm_driver#(apb_item);
  `uvm_component_utils(apb_driver)
  virtual apb_if vif;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))`uvm_fatal("VIF","missing interface")
  endfunction
  task run_phase(uvm_phase phase);
   apb_item t;
   forever begin
    seq_item_port.get_next_item(t);
    @(negedge vif.clk);vif.psel=1;vif.penable=0;vif.pwrite=t.write;vif.paddr=t.addr;vif.pwdata=t.data;
    @(negedge vif.clk);vif.penable=1;
    do begin @(posedge vif.clk);end while(!vif.pready);
    t.rdata=vif.prdata;t.error=vif.pslverr;
    @(negedge vif.clk);vif.psel=0;vif.penable=0;
    seq_item_port.item_done();
   end
  endtask
 endclass
 class apb_monitor extends uvm_monitor;
  `uvm_component_utils(apb_monitor)
  virtual apb_if vif;uvm_analysis_port#(apb_item) observed;
  function new(string n,uvm_component p);super.new(n,p);observed=new("observed",this);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))`uvm_fatal("VIF","missing interface")
  endfunction
  task run_phase(uvm_phase phase);
   forever begin
    apb_item t;@(posedge vif.clk);t=apb_item::type_id::create("sample");
    t.reset=!vif.rst_n;t.done=vif.psel&&vif.penable&&vif.pready;
    t.write=vif.pwrite;t.addr=vif.paddr;t.data=vif.pwdata;t.rdata=vif.prdata;t.error=vif.pslverr;t.events=vif.events;
    #1;t.actual_config=vif.config_value;t.actual_pending=vif.pending;observed.write(t);
   end
  endtask
 endclass
 class apb_agent extends uvm_agent;
  `uvm_component_utils(apb_agent)
  uvm_sequencer#(apb_item) sequencer;apb_driver driver;apb_monitor monitor;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);sequencer=new("sequencer",this);driver=apb_driver::type_id::create("driver",this);monitor=apb_monitor::type_id::create("monitor",this);
  endfunction
  function void connect_phase(uvm_phase phase);driver.seq_item_port.connect(sequencer.seq_item_export);endfunction
 endclass
 class apb_adapter extends uvm_reg_adapter;
  `uvm_object_utils(apb_adapter)
  function new(string n="apb_adapter");super.new(n);supports_byte_enable=0;provides_responses=0;endfunction
  virtual function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
   apb_item t=apb_item::type_id::create("reg_access");t.write=rw.kind==UVM_WRITE;t.addr=rw.addr[7:0];t.data=rw.data[31:0];return t;
  endfunction
  virtual function void bus2reg(uvm_sequence_item item,ref uvm_reg_bus_op rw);
   apb_item t;if(!$cast(t,item))`uvm_fatal("ADAPTER","wrong transaction type")
   rw.kind=t.write ? UVM_WRITE:UVM_READ;rw.addr=t.addr;rw.data=t.write ? t.data:t.rdata;rw.status=t.error ? UVM_NOT_OK:UVM_IS_OK;
  endfunction
 endclass
 class word_reg extends uvm_reg;
  `uvm_object_utils(word_reg)
  uvm_reg_field value;
  function new(string n="word_reg");super.new(n,32,UVM_NO_COVERAGE);endfunction
  function void build(string access="RW",int width=32,uvm_reg_data_t reset_value=0);
   value=uvm_reg_field::type_id::create("value");value.configure(this,width,0,access,0,reset_value,1,0,0);
  endfunction
 endclass
 class apb_block extends uvm_reg_block;
  `uvm_object_utils(apb_block)
  word_reg cfg,idreg,pend;
  function new(string n="apb_block");super.new(n,UVM_NO_COVERAGE);endfunction
  function void build();
   default_map=create_map("map",0,4,UVM_LITTLE_ENDIAN);
   cfg=word_reg::type_id::create("cfg");cfg.configure(this);cfg.build();default_map.add_reg(cfg,0,"RW");
   idreg=word_reg::type_id::create("idreg");idreg.configure(this);idreg.build("RO",32,'h41504233);default_map.add_reg(idreg,4,"RO");
   pend=word_reg::type_id::create("pend");pend.configure(this);pend.build("W1C",4);default_map.add_reg(pend,8,"RW");lock_model();
  endfunction
 endclass
 class apb_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(apb_scoreboard)
  uvm_analysis_imp#(apb_item,apb_scoreboard) observed;apb_block model;
  bit [31:0] cfg=0;bit [3:0] pending=0;int checks=0,transactions=0,reads=0,writes=0,errors=0;
  bit seen_write=0,seen_event=0;
  function new(string n,uvm_component p);super.new(n,p);observed=new("observed",this);endfunction
  function void write(apb_item t);
   bit bad;bit [31:0] expected;
   if(t.reset)begin cfg=0;pending=0;end
   else begin
    if(t.done)begin
     transactions++;if(t.write)writes++;else reads++;
     bad=!(t.addr inside {0,4,8}) || (t.write && t.addr==4);
     expected=t.addr==0 ? cfg:t.addr==4 ? 'h41504233:t.addr==8 ? {28'b0,pending}:0;
     if(t.error!=bad)begin $display("CHECK_FAIL UVM_RESPONSE");`uvm_fatal("UVM_RESPONSE","APB error differs") end
     if(!t.write && t.rdata!==expected)begin $display("CHECK_FAIL UVM_READ");`uvm_fatal("UVM_READ","read differs") end
     if(bad)begin errors++;$display("COVER access/error");end
     if(!bad && t.write && t.addr==0)begin cfg=t.data;seen_write=1;$display("COVER config/write");end
     if(!bad && !t.write && t.addr==0 && seen_write)$display("COVER config/readback");
     if(!bad && !t.write && t.addr==4)$display("COVER access/id");
     if(!bad && t.write && t.addr==8)begin
      if((t.data[3:0]&t.events)!=0)$display("COVER pending/event-wins");
      if(pending!=0 && t.events==0)$display("COVER pending/clear");
      pending=pending&~t.data[3:0];
     end
    end
    if(t.events!=0)begin seen_event=1;$display("COVER pending/event");end
    pending=pending|t.events;
   end
   if(t.actual_config!==cfg)begin $display("CHECK_FAIL UVM_CONFIG");`uvm_fatal("UVM_CONFIG","configuration/state differs") end
   if(t.actual_pending!==pending)begin $display("CHECK_FAIL UVM_PENDING");`uvm_fatal("UVM_PENDING","pending state differs") end
   checks++;
  endfunction
 endclass
 class raw_sequence extends uvm_sequence#(apb_item);
  `uvm_object_utils(raw_sequence)
  bit write;bit [7:0] addr;bit [31:0] data;
  function new(string n="raw_sequence");super.new(n);endfunction
  task body();apb_item t=apb_item::type_id::create("raw");start_item(t);t.write=write;t.addr=addr;t.data=data;finish_item(t);endtask
 endclass
 class apb_env extends uvm_env;
  `uvm_component_utils(apb_env)
  apb_agent agent;apb_scoreboard scoreboard;apb_block model;apb_adapter adapter;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);agent=apb_agent::type_id::create("agent",this);scoreboard=apb_scoreboard::type_id::create("scoreboard",this);
   model=apb_block::type_id::create("model");model.build();adapter=apb_adapter::type_id::create("adapter");scoreboard.model=model;
  endfunction
  function void connect_phase(uvm_phase phase);
   agent.monitor.observed.connect(scoreboard.observed);model.default_map.set_sequencer(agent.sequencer,adapter);model.default_map.set_auto_predict(1);
  endfunction
 endclass
 class apb_test extends uvm_test;
  `uvm_component_utils(apb_test)
  apb_env env;virtual apb_if vif;int iterations=8;int seed=17;bit bad_expected=0;bit finished=0;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);env=apb_env::type_id::create("env",this);
   if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))`uvm_fatal("VIF","missing interface")
   void'($value$plusargs("ITERATIONS=%d",iterations));void'($value$plusargs("SEED=%d",seed));void'($value$plusargs("BAD_EXPECTED=%d",bad_expected));
  endfunction
  task good(uvm_status_e status);
   if(status!=UVM_IS_OK)begin $display("CHECK_FAIL UVM_STATUS");`uvm_fatal("UVM_STATUS","frontdoor operation failed") end
  endtask
  task reset_dut();
   @(negedge vif.clk);vif.rst_n=0;vif.events=0;repeat(3)@(negedge vif.clk);env.model.reset();vif.rst_n=1;@(negedge vif.clk);
  endtask
  task raw(bit wr,bit[7:0] addr,bit[31:0] data);
   raw_sequence s=raw_sequence::type_id::create("s");s.write=wr;s.addr=addr;s.data=data;s.start(env.agent.sequencer);
  endtask
  task run_phase(uvm_phase phase);
   uvm_status_e status;uvm_reg_data_t value;int unsigned state;
   phase.raise_objection(this);state=seed;reset_dut();
   env.model.idreg.read(status,value,UVM_FRONTDOOR);good(status);
   if(status!=UVM_IS_OK || value!= (bad_expected ? 'hdeadbeef:'h41504233))begin $display("CHECK_FAIL UVM_EXPECTATION");`uvm_fatal("UVM_EXPECTATION","ID differs") end
   env.model.cfg.write(status,'h12345678,UVM_FRONTDOOR);good(status);env.model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);$display("COVER ral/mirror");
   @(negedge vif.clk);vif.events=3;
   env.model.pend.write(status,3,UVM_FRONTDOOR);good(status);
   @(negedge vif.clk);vif.events=0;#2;
   if(!env.model.pend.predict(env.scoreboard.pending))`uvm_fatal("PREDICT","hardware event prediction failed")
   env.model.pend.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);
   env.model.pend.write(status,15,UVM_FRONTDOOR);good(status);env.model.pend.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);
   raw(1,4,32'hdeadbeef);raw(0,12,0);
   for(int i=0;i<iterations;i++)begin
    state=state*1664525+1013904223;env.model.cfg.write(status,state,UVM_FRONTDOOR);good(status);env.model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);
   end
   reset_dut();env.model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);$display("COVER reset/mirror");
   repeat(2)@(negedge vif.clk);finished=1;phase.drop_objection(this);
  endtask
  function void report_phase(uvm_phase phase);
   uvm_report_server server=uvm_report_server::get_server();
   if(!finished || env.scoreboard.checks==0 || server.get_severity_count(UVM_ERROR)!=0 || server.get_severity_count(UVM_FATAL)!=0)begin $display("CHECK_FAIL UVM_REPORT");return;end
   $display("COUNT transactions=%0d",env.scoreboard.transactions);$display("COUNT reads=%0d",env.scoreboard.reads);$display("COUNT writes=%0d",env.scoreboard.writes);$display("COUNT errors=%0d",env.scoreboard.errors);
   $display("RESULT PASS checks=%0d",env.scoreboard.transactions);
  endfunction
 endclass
endpackage
