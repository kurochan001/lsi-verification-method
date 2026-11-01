`timescale 1ps/1ps
`include "uvm_macros.svh"
package oo_pkg;
 import uvm_pkg::*;
 class fatal_to_exit extends uvm_report_catcher;
  function new(string n="fatal_to_exit");super.new(n);endfunction
  virtual function action_e catch();if(get_severity()==UVM_FATAL)$fatal(1,"UVM_FATAL %s",get_id());return THROW;endfunction
 endclass
 class oo_control extends uvm_object;
  `uvm_object_utils(oo_control)
  bit stall=1,force_ready,stop_sink;
  function new(string n="oo_control");super.new(n);endfunction
 endclass
 class oo_config extends uvm_object;
  `uvm_object_utils(oo_config)
  virtual oo_if vif;oo_control control;int role;
  function new(string n="oo_config");super.new(n);endfunction
 endclass
 class oo_item extends uvm_sequence_item;
  `uvm_object_utils(oo_item)
  bit [1:0]id;bit [15:0]token;bit [7:0]data;bit ready,rst_n,release_enable;
  function new(string n="oo_item");super.new(n);endfunction
 endclass
 class oo_sample extends uvm_object;
  `uvm_object_utils(oo_sample)
  int kind,cycle;bit [1:0]id;bit [15:0]token;bit [7:0]data;bit rst_n;
  function new(string n="oo_sample");super.new(n);endfunction
 endclass
 class oo_driver extends uvm_driver#(oo_item);
  `uvm_component_utils(oo_driver)
  oo_config cfg;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  task run_phase(uvm_phase phase);
   forever begin
    oo_item t;seq_item_port.get_next_item(t);
    case(cfg.role)
     0:begin
      int waited=0;
      @(negedge cfg.vif.clk);cfg.vif.s_valid=1;cfg.vif.s_id=t.id;cfg.vif.s_token=t.token;cfg.vif.s_data=t.data;
      do begin @(posedge cfg.vif.clk);waited++;if(waited>1000)`uvm_fatal("OO_DRIVER","source handshake timed out") end
      while(!cfg.vif.rst_n || !cfg.vif.s_ready);
      @(negedge cfg.vif.clk);cfg.vif.s_valid=0;
     end
     1:begin
      @(negedge cfg.vif.clk);cfg.vif.m_ready=cfg.control.stall ? 0:cfg.control.force_ready ? 1:t.ready;
      @(posedge cfg.vif.clk);#1;
     end
     2:begin @(negedge cfg.vif.clk);cfg.vif.rst_n=t.rst_n;cfg.vif.release_enable=t.release_enable;end
     default:`uvm_fatal("OO_CFG","unknown role")
    endcase
    seq_item_port.item_done();
   end
  endtask
 endclass
 class oo_monitor extends uvm_monitor;
  `uvm_component_utils(oo_monitor)
  virtual oo_if vif;uvm_analysis_port#(oo_sample) observed;int cycle,completions;bit previous_reset;
  function new(string n,uvm_component p);super.new(n,p);observed=new("observed",this);endfunction
  function void publish(int kind);
   oo_sample t=oo_sample::type_id::create("observation");int off;
   t.kind=kind;t.cycle=cycle;t.rst_n=vif.rst_n;
   if(kind==0)begin t.id=vif.s_id;t.token=vif.s_token;t.data=vif.s_data;end
   if(kind==1)begin t.id=vif.m_id;t.token=vif.m_token;t.data=vif.m_data;end
   if(kind==2)$display("OO_RESET cycle=%0d rst=%0d",cycle,t.rst_n);
   else $display("OO_OBS kind=%0d cycle=%0d id=%0d token=%0d data=%0d",kind,cycle,t.id,t.token,t.data);
   void'($value$plusargs("CHECKER_OFF=%d",off));
   if(!(off==1 && kind==0) && off!=2)observed.write(t);
  endfunction
  task run_phase(uvm_phase phase);
   forever begin
    @(posedge vif.clk);cycle++;
    if(vif.rst_n!=previous_reset)begin publish(2);previous_reset=vif.rst_n;end
    if(vif.rst_n)begin
     if(vif.s_valid && vif.s_ready)publish(0);
     if(vif.m_valid && vif.m_ready)begin completions++;publish(1);end
    end
   end
  endtask
 endclass
 class oo_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(oo_scoreboard)
  uvm_analysis_imp#(oo_sample,oo_scoreboard) observed;
  int expected[int],tokens[int],orders[int],epochs[int];bit seen_token[int],seen_id[int];
  int accepted,produced,cancelled,epoch,peak,overtakes,reused;
  function new(string n,uvm_component p);super.new(n,p);observed=new("observed",this);endfunction
  function void fail(string id,string text);$display("CHECK_FAIL %s",id);`uvm_fatal(id,text) endfunction
  function void write(oo_sample t);
   int id=int'(t.id);
   if(t.kind==2)begin
    if(!t.rst_n)begin cancelled+=expected.num();epoch++;expected.delete();tokens.delete();orders.delete();epochs.delete();end
   end else if(t.kind==0)begin
    if(expected.exists(id))fail("OO_BUSY","accepted an occupied ID");
    if(seen_token.exists(int'(t.token)))fail("OO_TOKEN","transaction token reused");
    if(seen_id.exists(id))reused++;
    seen_id[id]=1;seen_token[int'(t.token)]=1;
    expected[id]=(int'(t.data)+int'(t.data)+int'(t.data)+id)&255;tokens[id]=int'(t.token);epochs[id]=epoch;orders[id]=accepted;accepted++;
    if(expected.num()>peak)peak=expected.num();if(peak>4)fail("OO_COUNTS","too many outstanding requests");
   end else if(t.kind==1)begin
    int oldest=32'h7fffffff;
    if(!expected.exists(id))fail("OO_UNKNOWN","unknown, duplicate or cancelled completion");
    if(tokens[id]!=int'(t.token) || epochs[id]!=epoch)fail("OO_TOKEN","completion belongs to another transaction");
    if(expected[id]!=int'(t.data))fail("OO_DATA","completion value differs");
    foreach(orders[k])if(orders[k]<oldest)oldest=orders[k];
    if(orders[id]!=oldest)overtakes++;
    expected.delete(id);tokens.delete(id);orders.delete(id);epochs.delete(id);produced++;
   end else fail("OO_OBSERVER","unknown observation type");
   if(accepted!=produced+cancelled+expected.num())fail("OO_COUNTS","accept/complete/cancel ledger differs");
  endfunction
 endclass
 class oo_agent extends uvm_agent;
  `uvm_component_utils(oo_agent)
  oo_config cfg;oo_driver driver;uvm_sequencer#(oo_item) sequencer;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);
   if(!uvm_config_db#(oo_config)::get(this,"","cfg",cfg) || cfg==null || cfg.vif==null || cfg.control==null)`uvm_fatal("OO_CFG","missing configuration")
   driver=oo_driver::type_id::create("driver",this);driver.cfg=cfg;sequencer=new("sequencer",this);
  endfunction
  function void connect_phase(uvm_phase phase);driver.seq_item_port.connect(sequencer.seq_item_export);endfunction
 endclass
 class oo_env extends uvm_env;
  `uvm_component_utils(oo_env)
  virtual oo_if vif;oo_control control;oo_agent agents[3];oo_monitor monitor;oo_scoreboard scoreboard;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   string names[3]='{"source","sink","control"};super.build_phase(phase);
   if(!uvm_config_db#(virtual oo_if)::get(this,"","vif",vif))`uvm_fatal("OO_CFG","missing interface")
   control=oo_control::type_id::create("control");scoreboard=oo_scoreboard::type_id::create("scoreboard",this);monitor=oo_monitor::type_id::create("monitor",this);monitor.vif=vif;
   for(int i=0;i<3;i++)begin
    oo_config c=oo_config::type_id::create(names[i]);c.vif=vif;c.control=control;c.role=i;
    uvm_config_db#(oo_config)::set(this,names[i],"cfg",c);agents[i]=oo_agent::type_id::create(names[i],this);
   end
  endfunction
  function void connect_phase(uvm_phase phase);monitor.observed.connect(scoreboard.observed);endfunction
 endclass
 class oo_single extends uvm_sequence#(oo_item);
  `uvm_object_utils(oo_single)
  oo_item item;
  function new(string n="oo_single");super.new(n);endfunction
  task body();start_item(item);finish_item(item);endtask
 endclass
 class oo_sink extends uvm_sequence#(oo_item);
  `uvm_object_utils(oo_sink)
  oo_control control;int unsigned state;
  function new(string n="oo_sink");super.new(n);endfunction
  task body();while(!control.stop_sink)begin
   oo_item t=oo_item::type_id::create("ready");start_item(t);state=state*1664525+1013904223;t.ready=state[3:2]!=0;finish_item(t);
  end endtask
 endclass
 class oo_virtual extends uvm_sequence#(uvm_sequence_item);
  `uvm_object_utils(oo_virtual)
  oo_env env;int rounds,next_token=1;int unsigned state;
  function new(string n="oo_virtual");super.new(n);endfunction
  task clocks(int n);repeat(n)@(negedge env.vif.clk);endtask
  task configure(bit reset_n,bit release_en);
   oo_single s=oo_single::type_id::create("configuration");s.item=oo_item::type_id::create("values");s.item.rst_n=reset_n;s.item.release_enable=release_en;s.start(env.agents[2].sequencer);
  endtask
  task batch();
   for(int id=0;id<4;id++)begin
    oo_single s=oo_single::type_id::create("send");s.item=oo_item::type_id::create("request");state=state*1664525+1013904223;
    s.item.id=2'(id);s.item.token=16'(next_token++);s.item.data=state[23:16];
    $display("OO_ISSUED id=%0d token=%0d data=%0d",s.item.id,s.item.token,s.item.data);s.start(env.agents[0].sequencer);
   end
  endtask
  task drain(int goal);
   for(int i=0;i<1000;i++)begin clocks(1);if(env.monitor.completions>=goal && env.scoreboard.expected.num()==0 && !env.vif.m_valid)return;end
   env.scoreboard.fail("OO_DRAIN","end of test still has unmatched requests");
  endtask
  task body();
   int off;void'($value$plusargs("CHECKER_OFF=%d",off));
   configure(0,0);clocks(3);configure(1,0);clocks(2);
   for(int r=0;r<rounds;r++)begin
    env.control.stall=1;configure(1,0);batch();clocks(8);configure(1,1);clocks(8);env.control.stall=0;drain(4*(r+1));
    if(r==rounds/2-1)begin
     env.control.stall=1;configure(1,0);batch();clocks(8);configure(0,0);clocks(2);configure(1,1);
     env.control.stall=0;env.control.force_ready=1;clocks(12);env.control.force_ready=0;
    end
   end
   drain(4*rounds);clocks(4);
   if(off==2 || env.scoreboard.accepted!=4*rounds+4 || env.scoreboard.produced!=4*rounds || env.scoreboard.cancelled!=4 || env.scoreboard.epoch!=1 || env.scoreboard.peak!=4 || env.scoreboard.overtakes<3*rounds || env.scoreboard.reused!=4*rounds || env.scoreboard.expected.num()!=0)
    env.scoreboard.fail("OO_COUNTS","completion, reuse, reorder or cancellation goals missing");
   $display("OO_COMPLETE accepted=%0d produced=%0d cancelled=4 epoch=1 peak=4 overtakes=%0d reused=%0d pending=0",env.scoreboard.accepted,env.scoreboard.produced,env.scoreboard.overtakes,env.scoreboard.reused);
   $display("RESULT PASS checks=%0d",env.scoreboard.accepted);
  endtask
 endclass
 class oo_test extends uvm_test;
  `uvm_component_utils(oo_test)
  oo_env env;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);super.build_phase(phase);env=oo_env::type_id::create("env",this);endfunction
  task run_phase(uvm_phase phase);
   oo_virtual sequence_all=oo_virtual::type_id::create("scenario");oo_sink sink=oo_sink::type_id::create("sink");int seed;
   phase.raise_objection(this);void'($value$plusargs("SEED=%d",seed));void'($value$plusargs("ROUNDS=%d",sequence_all.rounds));
   sequence_all.env=env;sequence_all.state=32'(seed);sink.control=env.control;sink.state=32'(seed)^32'ha13b;
   fork sink.start(env.agents[1].sequencer);begin sequence_all.start(null);env.control.stop_sink=1;end join
   phase.drop_objection(this);
  endtask
 endclass
endpackage
