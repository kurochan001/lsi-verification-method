`include "uvm_macros.svh"
package random_pkg;
 import uvm_pkg::*;import uvm_apb_pkg::*;
 class stimulus extends uvm_object;
  `uvm_object_utils(stimulus)
  rand bit write;rand bit [7:0] addr;rand bit [31:0] data;rand bit [3:0] events;
  constraint supported {addr inside {0,4,8,12};if(addr==8)data inside {[0:15]};events inside {0,1,3,15};}
  function new(string n="stimulus");super.new(n);endfunction
 endclass
 class collector extends uvm_subscriber#(apb_item);
  `uvm_component_utils(collector)
  bit disabled=0;int sampled=0,collision_samples=0;
  covergroup bus_cg with function sample(bit[1:0] address,bit write,bit error);
   option.per_instance=1;
   a:coverpoint address {bins cfg={0};bins idreg={1};bins pending={2};bins invalid={3};}
   w:coverpoint write {bins read={0};bins write={1};}
   e:coverpoint error {bins okay={0};bins error={1};}
   aw:cross a,w;
  endgroup
  covergroup collision_cg with function sample(bit event_seen,bit clear_seen);
   option.per_instance=1;
   e:coverpoint event_seen {bins absent={0};bins present={1};}
   c:coverpoint clear_seen {bins absent={0};bins present={1};}
   ec:cross e,c;
  endgroup
  function new(string n,uvm_component p);super.new(n,p);bus_cg=new();collision_cg=new();void'($value$plusargs("COVER_OFF=%d",disabled));endfunction
  function void write(apb_item t);
   if(!disabled && !t.reset && t.done)begin
    bus_cg.sample(t.addr[3:2],t.write,t.error);sampled++;
    if(t.addr==8 && t.write)begin collision_cg.sample(t.events!=0,t.data[3:0]!=0);collision_samples++;end
   end
  endfunction
 endclass
 class random_test extends apb_test;
  `uvm_component_utils(random_test)
  collector cov;int randomizations=0;bit bad_constraint=0;
  function new(string n,uvm_component p);super.new(n,p);endfunction
  function void build_phase(uvm_phase phase);
   super.build_phase(phase);cov=collector::type_id::create("cov",this);void'($value$plusargs("BAD_CONSTRAINT=%d",bad_constraint));
  endfunction
  function void connect_phase(uvm_phase phase);super.connect_phase(phase);env.agent.monitor.observed.connect(cov.analysis_export);endfunction
  task run_phase(uvm_phase phase);
   stimulus item=stimulus::type_id::create("item");bit ok;
   phase.raise_objection(this);item.srandom(seed);reset_dut();
   // Deterministic minimum plan covers every address/operation, then random history.
   for(int a=0;a<4;a++)for(int w=0;w<2;w++)raw(w!=0,8'(a*4),32'h12345678);
   for(int event_bit=0;event_bit<2;event_bit++)for(int clear_bit=0;clear_bit<2;clear_bit++)begin
    @(negedge vif.clk);vif.events=4'(event_bit);raw(1,8,32'(clear_bit));
    @(negedge vif.clk);vif.events=0;
   end
   for(int i=0;i<iterations;i++)begin
    if(bad_constraint)ok=item.randomize() with {addr==1;};else ok=item.randomize();
    if(!ok)begin $display("CHECK_FAIL CRV_RANDOMIZE");`uvm_fatal("CRV_RANDOMIZE","constraints could not be solved") end
    randomizations++;
    if(!(item.addr inside {0,4,8,12}) || !(item.events inside {0,1,3,15}) || (item.addr==8 && item.data>15))begin $display("CHECK_FAIL CRV_CONSTRAINT");`uvm_fatal("CRV_CONSTRAINT","constraint not respected") end
    $display("RANDOM addr=%0d write=%0d data=%08x events=%0d",item.addr,item.write,item.data,item.events);
    @(negedge vif.clk);vif.events=item.events;raw(item.write,item.addr,item.data);
    @(negedge vif.clk);vif.events=0;
   end
   repeat(2)@(negedge vif.clk);finished=1;phase.drop_objection(this);
  endtask
  function void report_phase(uvm_phase phase);
   if(cov.bus_cg.get_inst_coverage()!=100.0 || cov.collision_cg.get_inst_coverage()!=100.0)begin $display("CHECK_FAIL CRV_COVERAGE");`uvm_fatal("CRV_COVERAGE","native bins missing") end
   $display("NATIVE bus=%0.1f collision=%0.1f",cov.bus_cg.get_inst_coverage(),cov.collision_cg.get_inst_coverage());
   if(randomizations!=iterations || cov.sampled!=env.scoreboard.transactions)begin $display("CHECK_FAIL CRV_COUNTS");`uvm_fatal("CRV_COUNTS","sample count differs") end
   $display("COUNT randomizations=%0d",randomizations);
   super.report_phase(phase);
  endfunction
 endclass
endpackage
