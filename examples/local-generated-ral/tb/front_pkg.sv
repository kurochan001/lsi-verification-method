`include "uvm_macros.svh"
package front_pkg;
 import uvm_pkg::*;import uvm_apb_pkg::*;import rdl_pkg::*;
 class front_scoreboard extends uvm_scoreboard;
 `uvm_component_utils(front_scoreboard)
 uvm_analysis_imp#(apb_item,front_scoreboard) observed;
 bit[7:0]cfg=18;bit[3:0]pending=0;int transactions=0,reads=0,writes=0,errors=0;
 function new(string n,uvm_component p);super.new(n,p);observed=new("observed",this);endfunction
 function void write(apb_item t);
 bit bad;bit[31:0]expected;
 if(t.reset)begin cfg=18;pending=0;end else begin
 if(t.done)begin
 transactions++;if(t.write)writes++;else reads++;
 bad=!(t.addr inside {0,4,8}) || (t.write && t.addr==4);
 expected=t.addr==0 ? {24'b0,cfg}:t.addr==4 ? 32'h52444c31:t.addr==8 ? {28'b0,pending}:0;
 if(t.error!=bad)begin $display("CHECK_FAIL FRONT_RESPONSE");`uvm_fatal("FRONT_RESPONSE","error response differs") end
 if(!t.write && t.rdata!==expected)begin $display("CHECK_FAIL FRONT_READ");`uvm_fatal("FRONT_READ","independent register value differs") end
 if(bad)begin errors++;$display("COVER access/error");end
 if(!bad && t.write && t.addr==0)begin cfg=t.data[7:0];$display("COVER config/write");end
 if(!bad && !t.write && t.addr==4)$display("COVER id/read");
 if(!bad && t.write && t.addr==8)begin
 if((t.data[3:0]&t.events)!=0)$display("COVER pending/event-wins");
 if(pending!=0 && t.events==0)$display("COVER pending/clear");pending=pending&~t.data[3:0];end
 end
 if(t.events!=0)$display("COVER pending/event");pending=pending|t.events;
 end
 if(t.actual_config!=={24'b0,cfg})begin $display("CHECK_FAIL FRONT_STATE");`uvm_fatal("FRONT_STATE","config state differs") end
 if(t.actual_pending!==pending)begin $display("CHECK_FAIL FRONT_PENDING");`uvm_fatal("FRONT_PENDING","pending state differs") end
 endfunction endclass
 class front_env extends uvm_env;
 `uvm_component_utils(front_env)
 apb_agent agent;apb_adapter adapter;rdl_block model;front_scoreboard scoreboard;
 function new(string n,uvm_component p);super.new(n,p);endfunction
 function void build_phase(uvm_phase phase);
 super.build_phase(phase);agent=apb_agent::type_id::create("agent",this);adapter=apb_adapter::type_id::create("adapter");model=rdl_block::type_id::create("model");model.build();scoreboard=front_scoreboard::type_id::create("scoreboard",this);
 endfunction
 function void connect_phase(uvm_phase phase);agent.monitor.observed.connect(scoreboard.observed);model.default_map.set_sequencer(agent.sequencer,adapter);model.default_map.set_auto_predict(1);endfunction
 endclass
 class front_test extends uvm_test;
 `uvm_component_utils(front_test)
 front_env env;virtual apb_if vif;int iterations=12,seed=17;bit bad_mirror=0,finished=0;
 function new(string n,uvm_component p);super.new(n,p);endfunction
 function void build_phase(uvm_phase phase);
 super.build_phase(phase);env=front_env::type_id::create("env",this);if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))`uvm_fatal("VIF","missing interface")
 void'($value$plusargs("ITERATIONS=%d",iterations));void'($value$plusargs("SEED=%d",seed));void'($value$plusargs("BAD_MIRROR=%d",bad_mirror));endfunction
 task good(uvm_status_e status);if(status!=UVM_IS_OK)begin $display("CHECK_FAIL FRONT_STATUS");`uvm_fatal("FRONT_STATUS","frontdoor operation failed") end endtask
 task reset_dut();@(negedge vif.clk);vif.rst_n=0;vif.events=0;repeat(3)@(negedge vif.clk);env.model.reset();vif.rst_n=1;@(negedge vif.clk);endtask
 task raw(bit wr,bit[7:0]addr,bit[31:0]data);raw_sequence s=raw_sequence::type_id::create("s");s.write=wr;s.addr=addr;s.data=data;s.start(env.agent.sequencer);endtask
 task run_phase(uvm_phase phase);
 uvm_status_e status;uvm_reg_data_t value;int unsigned state;
 phase.raise_objection(this);state=seed;reset_dut();
 env.model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);$display("COVER reset/mirror");
 if(bad_mirror)begin void'(env.model.cfg.predict(0));env.model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);end
 env.model.idreg.read(status,value,UVM_FRONTDOOR);good(status);
 if(value!=32'h52444c31)begin $display("CHECK_FAIL FRONT_EXPECTATION");`uvm_fatal("FRONT_EXPECTATION","independent ID differs") end
 env.model.cfg.write(status,32'h6d,UVM_FRONTDOOR);good(status);env.model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);$display("COVER config/mirror");
 @(negedge vif.clk);vif.events=3;env.model.pending.write(status,3,UVM_FRONTDOOR);good(status);
 @(negedge vif.clk);vif.events=0;#2;
 if(!env.model.pending.predict(env.scoreboard.pending))`uvm_fatal("PREDICT","event prediction failed")
 env.model.pending.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);
 env.model.pending.write(status,15,UVM_FRONTDOOR);good(status);env.model.pending.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);
 raw(1,4,32'hdeadbeef);raw(0,12,0);
 for(int i=0;i<iterations;i++)begin state=state*1664525+1013904223;env.model.cfg.write(status,state&255,UVM_FRONTDOOR);good(status);env.model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);end
 reset_dut();env.model.cfg.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);env.model.pending.mirror(status,UVM_CHECK,UVM_FRONTDOOR);good(status);$display("COVER reset/recovery");
 repeat(2)@(negedge vif.clk);finished=1;phase.drop_objection(this);
 endtask
 function void report_phase(uvm_phase phase);
 uvm_report_server server=uvm_report_server::get_server();
 if(!finished || server.get_severity_count(UVM_ERROR)!=0 || server.get_severity_count(UVM_FATAL)!=0)begin $display("CHECK_FAIL FRONT_REPORT");`uvm_fatal("FRONT_REPORT","native UVM checks did not pass") end
 $display("COUNT transactions=%0d",env.scoreboard.transactions);$display("COUNT reads=%0d",env.scoreboard.reads);$display("COUNT writes=%0d",env.scoreboard.writes);$display("COUNT errors=%0d",env.scoreboard.errors);
 $display("RESULT PASS checks=%0d",env.scoreboard.transactions);
 endfunction endclass
endpackage
