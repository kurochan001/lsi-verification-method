`include "uvm_macros.svh"
package reg_seq_pkg;
 import uvm_pkg::*;
 // Label printed when the UVM library itself reports an error; the test sets it per stage.
 string stage_label="REG_SETUP";
 // Map UVM_ERROR and UVM_FATAL from the library to one labelled, nonzero exit.
 class stage_catcher extends uvm_report_catcher;
  function new(string n="stage_catcher");super.new(n);endfunction
  virtual function action_e catch();
   if(get_severity()==UVM_ERROR || get_severity()==UVM_FATAL)begin
    $display("LIBRARY_REPORT id=%s message=%s",get_id(),get_message());
    $display("CHECK_FAIL %s",stage_label);
    $fatal(1,"%s: %s",get_id(),get_message());
   end
   return THROW;
  endfunction
 endclass
 class bus_item extends uvm_sequence_item;
  `uvm_object_utils(bus_item)
  bit write;bit [7:0] addr;bit [31:0] data,rdata;bit error;
  function new(string name="bus_item");super.new(name);endfunction
 endclass
 class bus_driver extends uvm_driver#(bus_item);
  `uvm_component_utils(bus_driver)
  virtual regbus_if vif;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);if(!uvm_config_db#(virtual regbus_if)::get(this,"","vif",vif))`uvm_fatal("VIF","missing interface")
  endfunction
  task run_phase(uvm_phase phase);
   bus_item t;
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
 // The monitor only records. Every value is checked later by the Python model.
 class bus_monitor extends uvm_monitor;
  `uvm_component_utils(bus_monitor)
  virtual regbus_if vif;int unsigned age=0;bit in_reset=0;int reads=0,writes=0,errors=0;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);if(!uvm_config_db#(virtual regbus_if)::get(this,"","vif",vif))`uvm_fatal("VIF","missing interface")
  endfunction
  task run_phase(uvm_phase phase);
   forever begin
    @(posedge vif.clk);
    if(!vif.rst_n)begin
     if(!in_reset)$display("REGLOG RST");
     in_reset=1;age=0;
    end else begin
     in_reset=0;
     if(vif.psel && vif.penable && vif.pready)begin
      $display("REGLOG BUS age=%0d w=%0d addr=%0h wdata=%0h rdata=%0h err=%0d ev=%0h",age,vif.pwrite,vif.paddr,vif.pwdata,vif.prdata,vif.pslverr,vif.events);
      if(vif.pwrite)writes++;else reads++;
      if(vif.pslverr)errors++;
     end else if(vif.events!=0)$display("REGLOG EVT age=%0d ev=%0h",age,vif.events);
     age++;
    end
   end
  endtask
 endclass
 class bus_agent extends uvm_agent;
  `uvm_component_utils(bus_agent)
  uvm_sequencer#(bus_item) sequencer;bus_driver driver;bus_monitor monitor;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);sequencer=new("sequencer",this);driver=bus_driver::type_id::create("driver",this);monitor=bus_monitor::type_id::create("monitor",this);
  endfunction
  function void connect_phase(uvm_phase phase);driver.seq_item_port.connect(sequencer.seq_item_export);endfunction
 endclass
 class bus_adapter extends uvm_reg_adapter;
  `uvm_object_utils(bus_adapter)
  function new(string n="bus_adapter");super.new(n);supports_byte_enable=0;provides_responses=0;endfunction
  virtual function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
   bus_item t=bus_item::type_id::create("reg_access");t.write=rw.kind==UVM_WRITE;t.addr=rw.addr[7:0];t.data=rw.data[31:0];return t;
  endfunction
  virtual function void bus2reg(uvm_sequence_item bus_item,ref uvm_reg_bus_op rw);
   reg_seq_pkg::bus_item t;if(!$cast(t,bus_item))`uvm_fatal("ADAPTER","wrong transaction type")
   rw.kind=t.write ? UVM_WRITE:UVM_READ;rw.addr=t.addr;rw.data=t.write ? t.data:t.rdata;rw.status=t.error ? UVM_NOT_OK:UVM_IS_OK;
  endfunction
 endclass
 // One register class for every register: a single field with its own width, access and
 // volatility. The value bins are sampled by the RAL hook, not by the test.
 class word_reg extends uvm_reg;
  `uvm_object_utils(word_reg)
  uvm_reg_field value;string short_name;bit seen_zero,seen_ones,seen_other;bit [1:0] value_class;
  // Type-level covergroup: one set of bins shared by every register of this class. The
  // per-register goals are the COVER lines printed by sample() below.
  covergroup value_classes;
   coverpoint value_class { bins zero={0}; bins ones={1}; bins other={2}; }
  endgroup
  function new(string n="word_reg");super.new(n,32,build_coverage(UVM_CVR_FIELD_VALS));value_classes=new;endfunction
  function void build(string access,int width,uvm_reg_data_t reset_value,bit is_volatile);
   value=uvm_reg_field::type_id::create("value");value.configure(this,width,0,access,is_volatile,reset_value,1,0,0);
  endfunction
  protected virtual function void sample(uvm_reg_data_t data,uvm_reg_data_t byte_en,bit is_read,uvm_reg_map map);
   uvm_reg_data_t field_mask=(64'd1<<value.get_n_bits())-1;uvm_reg_data_t v=data&field_mask;
   if(!get_coverage(UVM_CVR_FIELD_VALS))return;
   value_class=v==0 ? 2'd0:v==field_mask ? 2'd1:2'd2;value_classes.sample();
   if(v==0 && !seen_zero)begin seen_zero=1;$display("COVER ral/value/%s/zero",short_name);end
   if(v==field_mask && !seen_ones)begin seen_ones=1;$display("COVER ral/value/%s/ones",short_name);end
   if(v!=0 && v!=field_mask && !seen_other)begin seen_other=1;$display("COVER ral/value/%s/other",short_name);end
  endfunction
 endclass
 class bank_mem extends uvm_mem;
  `uvm_object_utils(bank_mem)
  function new(string n="bank_mem");super.new(n,16,32,"RW",UVM_NO_COVERAGE);endfunction
 endclass
 class bank_block extends uvm_reg_block;
  `uvm_object_utils(bank_block)
  word_reg ctrl,idreg,status,irq,scratch,cmd;bank_mem ram;bit seen[string];
  function new(string n="bank_block");super.new(n,build_coverage(UVM_CVR_ADDR_MAP));endfunction
  function word_reg add(string name,int offset,string access,int width,uvm_reg_data_t reset_value,bit is_volatile,string rights);
   word_reg r=word_reg::type_id::create(name);r.short_name=name;r.configure(this);r.build(access,width,reset_value,is_volatile);default_map.add_reg(r,offset,rights);return r;
  endfunction
  function void build(bit status_volatile);
   default_map=create_map("map",0,4,UVM_LITTLE_ENDIAN);
   ctrl=add("ctrl",'h00,"RW",8,'ha5,0,"RW");
   idreg=add("id",'h04,"RO",32,'h52475351,0,"RO");
   status=add("status",'h08,"RO",8,0,status_volatile,"RO");
   irq=add("irq",'h0c,"W1C",4,0,0,"RW");
   scratch=add("scratch",'h10,"RW",32,0,0,"RW");
   cmd=add("cmd",'h14,"WO",1,0,0,"WO");
   ram=bank_mem::type_id::create("ram");ram.configure(this);default_map.add_mem(ram,'h40,"RW");
   lock_model();
  endfunction
  // Address-map coverage: called by the register layer for every frontdoor access.
  protected virtual function void sample(uvm_reg_addr_t offset,bit is_read,uvm_reg_map map);
   string name;
   if(!get_coverage(UVM_CVR_ADDR_MAP))return;
   case(offset)
    'h00:name="ctrl";'h04:name="id";'h08:name="status";'h0c:name="irq";'h10:name="scratch";'h14:name="cmd";
    default:name=(offset>='h40 && offset<'h80) ? "ram":"";
   endcase
   // The memory samples one word past each access in this library version; report it
   // separately instead of counting it as coverage.
   if(name=="")begin $display("RAL_SAMPLE_OUTSIDE offset=%0h",offset);return;end
   name={name,is_read ? "/read":"/write"};
   if(!seen.exists(name))begin seen[name]=1;$display("COVER ral/addr/%s",name);end
  endfunction
 endclass
 // User-defined backdoor through the interface. It replaces the HDL-path backdoor,
 // which needs the DPI routines that this build compiles off (UVM_NO_DPI).
 class probe_backdoor extends uvm_reg_backdoor;
  virtual regbus_if vif;bit target;
  function new(string n="probe_backdoor");super.new(n);endfunction
  virtual task read(uvm_reg_item rw);
   rw.value[0]=target ? vif.peek_scratch:{24'b0,vif.peek_ctrl};rw.status=UVM_IS_OK;
  endtask
  virtual function void read_func(uvm_reg_item rw);
   rw.value[0]=target ? vif.peek_scratch:{24'b0,vif.peek_ctrl};rw.status=UVM_IS_OK;
  endfunction
  virtual task write(uvm_reg_item rw);
   @(negedge vif.clk);vif.poke_target=target;vif.poke_value=rw.value[0][31:0];vif.poke=1;
   $display("REGLOG POKE target=%0d value=%0h",target,rw.value[0][31:0]);
   #1;vif.poke=0;rw.status=UVM_IS_OK;
  endtask
 endclass
 class raw_sequence extends uvm_sequence#(bus_item);
  `uvm_object_utils(raw_sequence)
  bit write;bit [7:0] addr;bit [31:0] data,rdata;bit error;
  function new(string n="raw_sequence");super.new(n);endfunction
  task body();bus_item t=bus_item::type_id::create("raw");start_item(t);t.write=write;t.addr=addr;t.data=data;finish_item(t);rdata=t.rdata;error=t.error;endtask
 endclass
 class bank_env extends uvm_env;
  `uvm_component_utils(bank_env)
  bus_agent agent;bank_block model;bus_adapter adapter;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   int status_nonvolatile=0,coverage_off=0;
   super.build_phase(phase);agent=bus_agent::type_id::create("agent",this);
   void'($value$plusargs("STATUS_NONVOLATILE=%d",status_nonvolatile));void'($value$plusargs("COVERAGE_OFF=%d",coverage_off));
   // Coverage models exist only when they are included before the model is created.
   if(!coverage_off)uvm_reg::include_coverage("*",UVM_CVR_ALL);
   model=bank_block::type_id::create("model");model.build(status_nonvolatile==0);
   if(!coverage_off)void'(model.set_coverage(UVM_CVR_ALL));
   adapter=bus_adapter::type_id::create("adapter");
  endfunction
  function void connect_phase(uvm_phase phase);
   model.default_map.set_sequencer(agent.sequencer,adapter);model.default_map.set_auto_predict(1);
  endfunction
 endclass
 class bank_test extends uvm_test;
  `uvm_component_utils(bank_test)
  bank_env env;virtual regbus_if vif;bit finished=0;int checks=0;
  int builtin_only=0,exclude_scratch=0,exclude_status=0,exclude_irq=0,events_during_bash=0,backdoor_mode=1,seed=17,iterations=4;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);env=bank_env::type_id::create("env",this);
   if(!uvm_config_db#(virtual regbus_if)::get(this,"","vif",vif))`uvm_fatal("VIF","missing interface")
   void'($value$plusargs("BUILTIN_ONLY=%d",builtin_only));void'($value$plusargs("EXCLUDE_SCRATCH=%d",exclude_scratch));
   void'($value$plusargs("EXCLUDE_STATUS=%d",exclude_status));void'($value$plusargs("EXCLUDE_IRQ=%d",exclude_irq));void'($value$plusargs("EVENTS_DURING_BASH=%d",events_during_bash));void'($value$plusargs("BACKDOOR=%d",backdoor_mode));
   void'($value$plusargs("SEED=%d",seed));void'($value$plusargs("ITERATIONS=%d",iterations));
  endfunction
  function void exclude(uvm_reg r,string name);
   uvm_resource_db#(bit)::set({"REG::",r.get_full_name()},name,1,this);$display("EXCLUDE %s %s",r.get_name(),name);
  endfunction
  function void stage(string name,string label);stage_label=label;$display("STAGE %s",name);endfunction
  task reset_dut();
   @(negedge vif.clk);vif.rst_n=0;vif.events=0;repeat(3)@(negedge vif.clk);env.model.reset();vif.rst_n=1;@(negedge vif.clk);
  endtask
  task raw(bit wr,bit[7:0] addr,bit[31:0] data,output bit[31:0] rdata,output bit error);
   raw_sequence s=raw_sequence::type_id::create("s");s.write=wr;s.addr=addr;s.data=data;s.start(env.agent.sequencer);rdata=s.rdata;error=s.error;
  endtask
  task good(uvm_status_e status,string label);
   if(status!=UVM_IS_OK)begin $display("CHECK_FAIL %s",label);$fatal(1,"frontdoor status");end
   checks++;
  endtask
  task expect_value(bit[31:0] actual,bit[31:0] expected,string label);
   if(actual!==expected)begin $display("CHECK_FAIL %s",label);$fatal(1,"read %h expected %h",actual,expected);end
   checks++;
  endtask
  task mirror_all(string name,string label);
   stage(name,label);check_mirror(label);
  endtask
  // Read every register except the volatile STATUS and compare it with the mirror.
  task check_mirror(string label);
   uvm_status_e status;uvm_reg regs[$];
   env.model.get_registers(regs);
   foreach(regs[i])if(regs[i]!=env.model.status)begin regs[i].mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status,label);end
  endtask
  task run_phase(uvm_phase phase);
   uvm_status_e status;uvm_reg_data_t value;bit [31:0] rdata;bit error;int unsigned state;
   uvm_reg_hw_reset_seq reset_seq;uvm_reg_bit_bash_seq bash_seq;uvm_mem_walk_seq walk_seq;uvm_reg_access_seq access_seq;
   probe_backdoor door;
   phase.raise_objection(this);state=seed;
   // Exclusions. Each one is listed with its reason in the README.
   if(exclude_scratch)exclude(env.model.scratch,"NO_REG_TESTS");
   if(exclude_status)exclude(env.model.status,"NO_REG_TESTS");
   if(exclude_irq)exclude(env.model.irq,"NO_REG_BIT_BASH_TEST");
   exclude(env.model.idreg,"NO_REG_ACCESS_TEST");exclude(env.model.status,"NO_REG_ACCESS_TEST");
   exclude(env.model.irq,"NO_REG_ACCESS_TEST");exclude(env.model.cmd,"NO_REG_ACCESS_TEST");
   reset_dut();
   stage("hw_reset","REG_RESET");reset_seq=uvm_reg_hw_reset_seq::type_id::create("reset_seq");reset_seq.model=env.model;reset_seq.start(null);$display("COVER builtin/hw-reset");
   // Register access through both doors. Mode 1 uses the user-defined backdoor, mode 2 only
   // declares HDL paths (needs the DPI routines), mode 0 gives the registers no backdoor.
   // Without any backdoor the block-level sequence only warns and skips the register.
   stage("access","REG_ACCESS");
   if(backdoor_mode==1 || backdoor_mode==3)begin
    // Mode 3 crosses the two observation points to show that the backdoor comparison is live.
    door=new("ctrl_door");door.vif=vif;door.target=backdoor_mode==3;env.model.ctrl.set_backdoor(door);
    door=new("scratch_door");door.vif=vif;door.target=backdoor_mode!=3;env.model.scratch.set_backdoor(door);
   end else if(backdoor_mode==2)begin
    env.model.add_hdl_path("top.mutant[0].dut");env.model.ctrl.add_hdl_path_slice("ctrl",0,8);env.model.scratch.add_hdl_path_slice("scratch",0,32);
   end
   access_seq=uvm_reg_access_seq::type_id::create("access_seq");access_seq.model=env.model;access_seq.start(null);$display("COVER builtin/access");
   // Leave the reset state before bit bashing: a bit bash returns every register to the value
   // it started from, so side effects that restore reset values would otherwise be invisible.
   stage("preload","REG_SETUP");
   env.model.ctrl.write(status,8'h3d,UVM_FRONTDOOR);good(status,"REG_SETUP");env.model.scratch.write(status,32'hcafe_f0dd,UVM_FRONTDOOR);good(status,"REG_SETUP");
   // Optional hardware events while the bit bash runs: the reason to exclude a register
   // that hardware can set at any time.
   if(events_during_bash)fork begin:event_source
    forever begin repeat(40)@(negedge vif.clk);vif.events=4'h2;@(negedge vif.clk);vif.events=0;end
   end join_none
   stage("bit_bash","REG_BITBASH");bash_seq=uvm_reg_bit_bash_seq::type_id::create("bash_seq");bash_seq.model=env.model;bash_seq.start(null);$display("COVER builtin/bit-bash");
   if(events_during_bash)begin disable event_source;@(negedge vif.clk);vif.events=0;end
   stage("mem_walk","MEM_WALK");walk_seq=uvm_mem_walk_seq::type_id::create("walk_seq");walk_seq.model=env.model;walk_seq.start(null);$display("COVER builtin/mem-walk");
   if(!builtin_only)begin
    // 1. Every register against its mirror after the built-in sequences have finished.
    mirror_all("mirror_after_builtin","REG_MIRROR");$display("COVER directed/mirror");
    // 2. Seeded writes to the two read-write registers, then one check of all registers.
    stage("cross_register","REG_MIRROR");
    env.model.ctrl.write(status,8'h00,UVM_FRONTDOOR);good(status,"REG_MIRROR");env.model.scratch.write(status,32'hffff_ffff,UVM_FRONTDOOR);good(status,"REG_MIRROR");check_mirror("REG_MIRROR");
    env.model.ctrl.write(status,8'hff,UVM_FRONTDOOR);good(status,"REG_MIRROR");env.model.scratch.write(status,32'h0,UVM_FRONTDOOR);good(status,"REG_MIRROR");check_mirror("REG_MIRROR");
    for(int i=0;i<iterations;i++)begin
     state=state*1664525+1013904223;env.model.ctrl.write(status,state[23:16],UVM_FRONTDOOR);good(status,"REG_MIRROR");
     state=state*1664525+1013904223;env.model.scratch.write(status,state,UVM_FRONTDOOR);good(status,"REG_MIRROR");
     check_mirror("REG_MIRROR");
    end
    $display("COVER directed/cross-register");
    // 3. Every unmapped word address must answer with an error and change nothing.
    stage("unmapped","REG_ALIAS");
    for(int a='h18;a<'h100;a+=4)if(a<'h40 || a>='h80)begin
     raw(1,a[7:0],32'hffff_ffff^a,rdata,error);if(!error)begin $display("CHECK_FAIL REG_ALIAS");$fatal(1,"write to unmapped %h accepted",a);end
     raw(0,a[7:0],0,rdata,error);if(!error)begin $display("CHECK_FAIL REG_ALIAS");$fatal(1,"read of unmapped %h accepted",a);end
     checks+=2;
    end
    mirror_all("unmapped_mirror","REG_ALIAS");$display("COVER directed/unmapped");
    // 4. W1C with hardware events: set all four bits, clear them one at a time, and let an
    //    event arrive in the same cycle as a clear.
    stage("w1c","REG_W1C");
    @(negedge vif.clk);vif.events=4'hf;@(negedge vif.clk);vif.events=0;
    env.model.irq.read(status,value,UVM_FRONTDOOR);good(status,"REG_W1C");expect_value(value[31:0],32'hf,"REG_W1C");
    for(int b=0;b<4;b++)begin
     env.model.irq.write(status,32'd1<<b,UVM_FRONTDOOR);good(status,"REG_W1C");
     env.model.irq.read(status,value,UVM_FRONTDOOR);good(status,"REG_W1C");expect_value(value[31:0],32'hf&~((32'd2<<b)-1),"REG_W1C");
    end
    $display("COVER directed/w1c-clear");
    env.model.irq.write(status,0,UVM_FRONTDOOR);good(status,"REG_W1C");
    @(negedge vif.clk);vif.events=4'h5;@(negedge vif.clk);vif.events=0;
    fork
     begin env.model.irq.write(status,32'h5,UVM_FRONTDOOR);end
     begin repeat(2)@(negedge vif.clk);vif.events=4'h1;@(negedge vif.clk);vif.events=0;end
    join
    good(status,"REG_W1C");
    env.model.irq.read(status,value,UVM_FRONTDOOR);good(status,"REG_W1C");expect_value(value[31:0],32'h1,"REG_W1C");
    env.model.irq.write(status,32'hf,UVM_FRONTDOOR);good(status,"REG_W1C");
    env.model.irq.read(status,value,UVM_FRONTDOOR);good(status,"REG_W1C");expect_value(value[31:0],32'h0,"REG_W1C");
    $display("COVER directed/w1c-event-wins");
    // 5. The command register: a soft reset returns three registers to their reset values.
    stage("soft_reset","REG_CMD");
    env.model.ctrl.write(status,8'h3c,UVM_FRONTDOOR);good(status,"REG_CMD");env.model.scratch.write(status,32'hcafe_f00d,UVM_FRONTDOOR);good(status,"REG_CMD");
    env.model.cmd.write(status,0,UVM_FRONTDOOR);good(status,"REG_CMD");
    check_mirror("REG_CMD");
    env.model.cmd.write(status,1,UVM_FRONTDOOR);good(status,"REG_CMD");
    // The model cannot know the side effect; the test tells it, then checks the hardware.
    void'(env.model.ctrl.predict('ha5));void'(env.model.scratch.predict(0));void'(env.model.irq.predict(0));
    check_mirror("REG_CMD");$display("COVER directed/soft-reset");
    // 6. A distinct value in every memory word, written first and read afterwards.
    stage("mem_unique","MEM_ALIAS");
    for(int k=0;k<16;k++)begin env.model.ram.write(status,k,32'h1000_0001*(k+1),UVM_FRONTDOOR);good(status,"MEM_ALIAS");end
    for(int k=0;k<16;k++)begin env.model.ram.read(status,k,value,UVM_FRONTDOOR);good(status,"MEM_ALIAS");expect_value(value[31:0],32'h1000_0001*(k+1),"MEM_ALIAS");end
    $display("COVER directed/mem-unique");
   end
   stage("done","REG_REPORT");
   repeat(2)@(negedge vif.clk);finished=1;phase.drop_objection(this);
  endtask
  function void report_phase(uvm_phase phase);
   uvm_report_server server=uvm_report_server::get_server();bus_monitor m=env.agent.monitor;
   if(!finished || server.get_severity_count(UVM_ERROR)!=0 || server.get_severity_count(UVM_FATAL)!=0)begin $display("CHECK_FAIL REG_REPORT");return;end
   $display("COUNT reads=%0d",m.reads);$display("COUNT writes=%0d",m.writes);$display("COUNT errors=%0d",m.errors);
   $display("RESULT PASS checks=%0d",m.reads+m.writes);
  endfunction
 endclass
endpackage
